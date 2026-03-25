import os
import re
import time
import base64
import asyncio
import aiohttp
import json
import tempfile
from .utils import calculate_score_weights
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Image as AstrImage
from astrbot.api import logger, AstrBotConfig
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import AiocqhttpMessageEvent

from .image_render import render_report

FLJ_API_BASE = "https://flj.info/api"
FLJ_VERIFY_URL = f"{FLJ_API_BASE}/verify"
FLJ_WEB_URL = "https://flj.info/verify"
REQUEST_TIMEOUT = 60  # flj.info 分析通常需要 20-30 秒
CACHE_TTL = 300  # 缓存 5 分钟


@register("astrbot_plugin_x_score", "X账号评分", "查询 X/Twitter 账号可信度评分", "1.2.0")
class FljPlugin(Star):
    """X账号评分插件 - 查询 X/Twitter 账号可信度评分"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._cache: dict[str, tuple[float, dict]] = {}  # username -> (timestamp, data)
        self._pending: dict[str, asyncio.Task] = {}  # username -> Task (并发去重)
        self._recall_tasks = set()  # 保存 asyncio.Task 强引用避免 GC 被意外回收
        self._session: aiohttp.ClientSession | None = None
        
    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT))
        return self._session

    @filter.command("X账号评分")
    async def query_x_account(self, event: AstrMessageEvent, username: str = ""):
        '''查询 X/Twitter 账号的可信度评分。用法：/X账号评分 <用户名>'''

        # 优先使用 AstrBot 提取的参数，若因别名失效解析不到，则采用正则兜底整句抓取
        username = username.strip()
        if not username:
            match = re.search(r'^\S+[\s]+(.*)', event.message_str.strip())
            if match:
                username = match.group(1).strip()
                
        if not username:
            yield event.plain_result(
                "❌ 请提供 X/Twitter 用户名。\n"
                "用法：/X账号评分 <用户名>\n"
                "示例：/X账号评分 elonmusk"
            )
            return

        # 去除可能带有的 @ 前缀
        username = username.lstrip("@")

        if not re.match(r"^[A-Za-z0-9_]{1,15}$", username):
            yield event.plain_result(
                f"❌ 用户名格式错误: '{username}'\n"
                "请输入有效的 X(Twitter) 用户名（仅支持英文、数字、下划线，最高15位）。\n"
                "注意：flj.info 目前不支持直接搜索中文昵称/显示名。"
            )
            return

        if self.config.get("show_analyze_alert", True):
            yield event.plain_result(f"正在分析 @{username}，请稍候...")

        try:
            data = await self._fetch_verify(username)
        except (TimeoutError, asyncio.TimeoutError):
            yield event.plain_result("❌ 请求超时（分析通常需要20-30秒），请稍后重试。")
            return
        except json.JSONDecodeError:
            logger.error("[X账号评分] API 返回的数据格式异常(非 JSON)")
            yield event.plain_result("❌ API 接口返回异常格式。")
            return
        except aiohttp.client_exceptions.ContentTypeError:
            logger.error("[X账号评分] API 返回的 Content-Type 异常")
            yield event.plain_result("❌ 远程接口维护中或网关故障(502/503)。")
            return
        except aiohttp.ClientResponseError as e:
            logger.error(f"[X账号评分] API 响应异常: HTTP {e.status}")
            if e.status == 429:
                yield event.plain_result(
                    "🚦 当前访问量过大\n"
                    "本小时内的 AI 分析额度已用完（保护公益资源）。\n"
                    "请在【下一整点】后再尝试新的检索。"
                )
            else:
                yield event.plain_result(f"❌ 网络请求失败 ({e.status})，请稍后重试。")
            return
        except aiohttp.ClientError as e:
            logger.error(f"[X账号评分] 网络异常: {type(e).__name__}")
            yield event.plain_result("❌ 网络请求失败，请稍后重试。")
            return

        if not data or "score" not in data:
            yield event.plain_result(
                f"❌ 未能获取 @{username} 的评分数据，该用户可能不存在。"
            )
            return

        # 预先生成 fallback_text 以防止未定义错误
        fallback_text = self._format_result(data)
        
        # 根据配置选择输出模式
        output_mode = self.config.get("output_mode", "图片")
        
        message_data = None
        img_bytes_cache = None
        
        if output_mode == "文字":
            message_data = [{"type": "text", "data": {"text": fallback_text}}]
        else:
            # 图片模式
            blur_media = self.config.get("blur_media", False)
            try:
                # 传入公用的 session 以复用连接
                session = self._get_session()
                img_bytes_cache = await render_report(session, data, blur_media=blur_media)
                img_base64 = base64.b64encode(img_bytes_cache).decode('utf-8')
                message_data = [{"type": "image", "data": {"file": f"base64://{img_base64}"}}]
            except Exception as e:
                logger.error(f"[X账号评分] 图片渲染失败: {type(e).__name__}: {e}")
                message_data = [{"type": "text", "data": {"text": fallback_text}}]

        # 调用独立的发送协程，彻底解耦业务流与分发链路
        async for reply in self._dispatch_message(event, message_data, fallback_text, img_bytes_cache):
            yield reply

    async def _dispatch_message(self, event: AstrMessageEvent, message_data: list, fallback_text: str, img_bytes_cache: bytes | None):
        """分发与发送引擎，支持平台特异性与通用降级，包含撤回调度"""
        recall_delay = self.config.get("recall_delay", 0)
        
        # 针对 aiocqhttp 平台使用更底层的 API 以确保获取 message_id 用于撤回
        if event.get_platform_name() == "aiocqhttp" and isinstance(event, AiocqhttpMessageEvent):
            try:
                client = event.bot
                group_id = event.get_group_id()
                
                if group_id:
                    resp = await client.send_group_msg(group_id=int(group_id), message=message_data)
                else:
                    resp = await client.send_private_msg(user_id=int(event.get_sender_id()), message=message_data)
                
                if resp and isinstance(resp, dict) and resp.get("message_id"):
                    msg_id = resp["message_id"]
                    if recall_delay > 0:
                        async def do_recall(m_id):
                            await asyncio.sleep(recall_delay)
                            try:
                                await client.api.call_action("delete_msg", message_id=m_id)
                            except Exception as ex:
                                logger.debug(f"[X账号评分] 撤回消息失败: {ex}")
                        
                        task = asyncio.create_task(do_recall(msg_id))
                        self._recall_tasks.add(task)
                        task.add_done_callback(self._recall_tasks.discard)
                    
                    return 
            except Exception as e:
                logger.error(f"[X账号评分] 原生发送组件失败，尝试通用下行降级: {e}")
        
        # 通用发送分支 (兜底或非 aiocqhttp 平台)
        try:
            if message_data[0]["type"] == "text":
                yield event.plain_result(fallback_text)
            elif message_data[0]["type"] == "image" and img_bytes_cache:
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(img_bytes_cache)
                    tmp_path = tmp.name
                    
                try:
                    chain = MessageChain([AstrImage.fromFileSystem(tmp_path)])
                    await self.context.send_message(event.unified_msg_origin, chain)
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
            else:
                yield event.plain_result(fallback_text)
        except Exception as e:
            logger.error(f"[X账号评分] 通用发送异常: {type(e).__name__}: {e}")
            yield event.plain_result(fallback_text)

    async def _fetch_verify(self, username: str) -> dict:
        """调用 flj.info 验证接口，带缓存和并发去重"""
        key = username.lower()
        
        # 1. 检查缓存
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < CACHE_TTL:
                logger.debug(f"[X账号评分] 缓存命中: @{username}")
                return data
            else:
                del self._cache[key]
        
        # 2. 并发去重
        if key in self._pending:
            logger.debug(f"[X账号评分] 合并请求: @{username}")
            return await self._pending[key]
        
        # 3. 发起新请求的后台任务
        task = asyncio.create_task(self._do_fetch_verify(username, key))
        self._pending[key] = task
        try:
            return await task
        finally:
            self._pending.pop(key, None)

    async def _do_fetch_verify(self, username: str, key: str) -> dict:
        params = {
            "username": username,
            "t": str(int(time.time() * 1000)),
            "lang": "zh",
            "source": "search",
        }
        logger.info(f"[X账号评分] 查询 @{username}")
        session = self._get_session()
        async with session.get(FLJ_VERIFY_URL, params=params) as resp:
            try:
                # 倒置顺序：先尝试解析 JSON，如果遇到 502/503 的 HTML，ContentTypeError 会优先抛出，避免被 ClientResponseError 吞噬
                data = await resp.json()
                resp.raise_for_status()
            except aiohttp.client_exceptions.ContentTypeError:
                raise
            except json.JSONDecodeError:
                raise
            except aiohttp.ClientResponseError:
                raise
            except Exception as e:
                # Catch any other unexpected errors during JSON parsing
                logger.error(f"[X账号评分] 解析 API 响应失败: {type(e).__name__}: {e}")
                raise
        
        score = data.get("score", "?")
        logger.info(f"[X账号评分] @{username} 评分: {score}")
        
        # 写入缓存，并限制最大缓存数量为 100
        self._cache[key] = (time.time(), data)
        if len(self._cache) > 100:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][0])
            del self._cache[oldest_key]
            
        return data

    def _format_result(self, data: dict) -> str:
        """纯文本格式（完整版，与图片版内容一致）"""
        score = data.get("score", "N/A")
        display_name = data.get("display_name", "未知")
        username = data.get("twitter_username", "未知")
        user_eval = str(data.get("user_eval", "暂无评价") or "暂无评价")
        bio = str(data.get("bio", "") or "")
        gender = data.get("gender", "")

        detail = data.get("score_detail") or {}
        followers = detail.get("followers") or 0
        following = detail.get("following") or 0
        tweets = detail.get("tweets") or 0
        try:
            account_age = float(detail.get("account_age_years", 0)) if detail.get("account_age_years") is not None else 0.0
        except (ValueError, TypeError):
            account_age = 0.0
        is_verified = detail.get("is_verified", False)
        is_welfare = detail.get("is_welfare", False)
        is_active = detail.get("is_active", False)
        engagement = detail.get("engagement") or ""
        positives = detail.get("positives") or 0
        complaints = detail.get("complaints") or 0
        pinned_has_url = detail.get("pinned_tweet_has_url", False)
        location = str(detail.get("location", "") or "")
        primary_language = str(detail.get("primary_language", "") or "")
        account_tags = detail.get("account_tags") or []

        negative_tags = [str(t) for t in (data.get("negative_tags") or [])]
        positive_tags = [str(t) for t in (data.get("positive_tags") or [])]
        is_fushi = data.get("is_fushi", False)
        has_threshold = data.get("has_threshold", False)

        pos_examples = data.get("positive_examples") or []
        neg_examples = data.get("complaint_examples") or []

        # 评分等级
        if isinstance(score, (int, float)):
            if score >= 90: level = "极为可信"
            elif score >= 75: level = "较为可信"
            elif score >= 60: level = "一般可信"
            elif score >= 40: level = "可信度低"
            else: level = "风险较高"
        else:
            level = "未知"

        # 标签
        tags = []
        tags.append("活跃" if is_active else "不活跃")
        if gender:
            g_text = {"male": "♂男", "female": "♀女"}.get(gender, gender)
            tags.append(g_text)
        if location: tags.append(location)
        if primary_language: tags.append(primary_language)
        if is_verified: tags.append("✓已认证")
        if is_welfare: tags.append("福利号")
        if is_fushi: tags.append("付费")
        if has_threshold: tags.append("有门槛")
        for t in account_tags: tags.append(str(t))
        for t in positive_tags: tags.append(str(t))
        for t in negative_tags: tags.append(str(t))

        lines = [
            f"📊 X 账号可信度报告",
            f"━━━━━━━━━━━━━━━━━━",
            f"👤 {display_name} (@{username})",
            f"🎯 评分：{score}/100（{level}）",
            f"",
            f"📋 {' | '.join(tags)}",
        ]

        if bio:
            lines.append(f"📝 {bio[:150]}{'...' if len(bio) > 150 else ''}")

        lines.extend([
            f"",
            f"👥 粉丝 {self._fmt_num(followers)} | 关注 {self._fmt_num(following)} | 推文 {self._fmt_num(tweets)} | 账龄 {account_age:.1f}年",
        ])

        # 评分明细
        eng_labels = {"high": "高", "medium": "中", "low": "低"}
        eng_level = eng_labels.get(engagement, "")
        
        weights = calculate_score_weights(
            account_age_years=account_age,
            followers=followers,
            tweets=tweets,
            is_verified=is_verified,
            is_active=is_active,
            engagement=engagement,
            positives=positives,
            complaints=complaints,
            pinned_has_url=pinned_has_url
        )
        b_age = weights["b_age"]
        b_fol = weights["b_fol"]
        b_twt = weights["b_twt"]
        b_ver = weights["b_ver"]
        b_act = weights["b_act"]
        b_eng = weights["b_eng"]
        b_pos = weights["b_pos"]
        b_neg = weights["b_neg"]
        b_pin = weights["b_pin"]
        
        age_label = f"{account_age:.1f}年" if account_age > 0 else "未知"
        pos_label = f"×{positives}" if positives > 0 else ""
        eng_display = f"（{eng_level}）" if eng_level else ""

        def _pts(v):
            return f"+{v}" if v > 0 else str(v)

        lines.extend([
            f"",
            f"📊 评分明细",
            f"  基础分　　　　　{_pts(20)}",
            f"  账号寿命（{age_label}）　{_pts(b_age)}",
            f"  粉丝量（{self._fmt_num(followers)}）　{_pts(b_fol)}",
            f"  发帖量（{self._fmt_num(tweets)}）　{_pts(b_twt)}",
            f"  蓝V认证　　　　{_pts(b_ver)}",
            f"  近期活跃发帖　　{_pts(b_act)}",
            f"  互动活跃度{eng_display}　{_pts(b_eng)}",
            f"  正面好评{pos_label}　　{_pts(b_pos)}",
            f"  负面评价　　　　{_pts(b_neg)}",
            f"  置顶推含外链　　{_pts(b_pin)}",
        ])

        # AI 评价
        lines.extend([
            f"",
            f"🤖 AI 可信度评价：",
            user_eval[:300] + ("..." if len(user_eval) > 300 else ""),
        ])

        # 正面评价
        if pos_examples:
            lines.append(f"")
            lines.append(f"👍 正面评价：")
            for ex in pos_examples[:5]:
                lines.append(f'  "{str(ex)[:100]}"')

        # 负面评价
        if neg_examples:
            lines.append(f"")
            lines.append(f"🚨 负面评价：")
            for ex in neg_examples[:5]:
                lines.append(f'  "{str(ex)[:100]}"')

        lines.extend([
            f"",
            f"⚠ 检索结果仅供参考",
            f"🔗 {FLJ_WEB_URL}/{username}",
        ])
        return "\n".join(lines)

    @staticmethod
    def _fmt_num(num) -> str:
        if not isinstance(num, (int, float)):
            return str(num)
        if num >= 100_000_000:
            return f"{num / 100_000_000:.1f}亿"
        elif num >= 10_000:
            return f"{num / 10_000:.1f}万"
        return str(int(num))

    async def terminate(self):
        """生命周期结束时的清理工作，释放连接池和回收挂起的任务"""
        if self._session and not self._session.closed:
            await self._session.close()
        
        # 稳妥地清理正在排队或挂起的任务
        tasks_to_cancel = []
        for t in self._pending.values():
            if not t.done():
                t.cancel()
                tasks_to_cancel.append(t)
        
        for t in self._recall_tasks:
            if not t.done():
                t.cancel()
                tasks_to_cancel.append(t)
        
        if tasks_to_cancel:
            # 在后台稍作等待，让被取消的任务妥善结束
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
            
        self._cache.clear()
        self._pending.clear()
        self._recall_tasks.clear()
