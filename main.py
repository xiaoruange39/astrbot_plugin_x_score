import os
import re
import time
import base64
import asyncio
import aiohttp
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


@register("astrbot_plugin_x_score", "X账号评分", "查询 X/Twitter 账号可信度评分", "1.1.2")
class FljPlugin(Star):
    """X账号评分插件 - 查询 X/Twitter 账号可信度评分"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._cache: dict[str, tuple[float, dict]] = {}  # username -> (timestamp, data)
        self._pending: dict[str, asyncio.Future] = {}  # username -> Future (并发去重)

    @filter.command("X账号评分")
    async def query_x_account(self, event: AstrMessageEvent):
        '''查询 X/Twitter 账号的可信度评分。用法：/X账号评分 <用户名>'''

        # event.message_str 包含完整消息，需要去掉指令名称部分
        raw = event.message_str.strip()
        # 去掉可能的指令前缀
        for prefix in ["X账号评分", "/X账号评分"]:
            if raw.startswith(prefix):
                raw = raw[len(prefix):].strip()
                break
        username = raw.strip()
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
        except aiohttp.ClientResponseError as e:
            logger.error(f"请求 flj.info API 失败: {e.status}, message='{e.message}'")
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
            logger.error(f"请求 flj.info API 失败: {e}")
            yield event.plain_result("❌ 网络请求失败，请稍后重试。")
            return
        except TimeoutError:
            yield event.plain_result("❌ 请求超时（分析通常需要20-30秒），请稍后重试。")
            return

        if not data or "score" not in data:
            yield event.plain_result(
                f"❌ 未能获取 @{username} 的评分数据，该用户可能不存在。"
            )
            return

        # 生成图片
        try:
            img_bytes = await render_report(data)
        except Exception as e:
            logger.error(f"生成报告图片失败: {e}")
            yield event.plain_result(self._format_result(data))
            return

        # 保存图片到临时文件
        tmp_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "..", "temp"
        )
        os.makedirs(tmp_dir, exist_ok=True)
        img_path = os.path.join(tmp_dir, f"x_score_{username}_{int(time.time())}.png")
        with open(img_path, "wb") as f:
            f.write(img_bytes)
        logger.info(f"图片已保存到临时路径: {img_path}")

        # 发送图片并处理撤回
        recall_delay = self.config.get("recall_delay", 0)
        
        # 针对 aiocqhttp 平台使用更底层的 API 以确保获取 message_id 用于撤回
        if event.get_platform_name() == "aiocqhttp" and isinstance(event, AiocqhttpMessageEvent):
            try:
                client = event.bot
                with open(img_path, "rb") as f:
                    img_base64 = base64.b64encode(f.read()).decode('utf-8')
                
                message = [{"type": "image", "data": {"file": f"base64://{img_base64}"}}]
                group_id = event.get_group_id()
                
                if group_id:
                    resp = await client.send_group_msg(group_id=int(group_id), message=message)
                else:
                    resp = await client.send_private_msg(user_id=int(event.get_sender_id()), message=message)
                
                if resp and isinstance(resp, dict) and resp.get("message_id"):
                    msg_id = resp["message_id"]
                    if recall_delay > 0:
                        async def do_recall(m_id):
                            await asyncio.sleep(recall_delay)
                            try:
                                await client.api.call_action("delete_msg", message_id=m_id)
                            except Exception:
                                pass
                        asyncio.create_task(do_recall(msg_id))
                    
                    # 发送成功后删除本地临时图片
                    if os.path.exists(img_path):
                        os.remove(img_path)
                    return 
            except Exception as e:
                logger.error(f"专属发送异常: {e}")

        # 回退到通用发送方式
        chain = MessageChain([AstrImage.fromFileSystem(img_path)])
        await self.context.send_message(event.unified_msg_origin, chain)
        
        # 发送结束后清理图片
        if os.path.exists(img_path):
            os.remove(img_path)

    async def _fetch_verify(self, username: str) -> dict:
        """调用 flj.info 验证接口，带缓存和并发去重"""
        key = username.lower()
        
        # 1. 检查缓存
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < CACHE_TTL:
                logger.info(f"命中缓存: @{username}")
                return data
            else:
                del self._cache[key]
        
        # 2. 并发去重：如果已有相同请求在进行中，等待其结果
        if key in self._pending:
            logger.info(f"等待已有请求: @{username}")
            return await self._pending[key]
        
        # 3. 发起新请求
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[key] = fut
        
        try:
            params = {
                "username": username,
                "t": str(int(time.time() * 1000)),
                "lang": "zh",
                "source": "search",
            }
            timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(FLJ_VERIFY_URL, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            
            # 写入缓存
            self._cache[key] = (time.time(), data)
            fut.set_result(data)
            return data
        except Exception as e:
            fut.set_exception(e)
            raise
        finally:
            self._pending.pop(key, None)

    def _format_result(self, data: dict) -> str:
        """纯文本格式（图片生成失败时的回退方案）"""
        score = data.get("score", "N/A")
        display_name = data.get("display_name", "未知")
        username = data.get("twitter_username", "未知")
        user_eval = str(data.get("user_eval", "暂无评价") or "暂无评价")
        
        detail = data.get("score_detail") or {}
        followers = detail.get("followers", 0)
        account_age = detail.get("account_age_years", 0)

        lines = [
            f"📊 X 账号可信度报告",
            f"👤 {display_name} (@{username})",
            f"🎯 评分：{score}/100",
            f"👥 粉丝：{self._fmt_num(followers)} | 账龄：{account_age:.1f}年",
            f"",
            f"🤖 AI 评价：",
            user_eval[:200] + ("..." if len(user_eval) > 200 else ""),
            f"",
            f"🔗 {FLJ_WEB_URL}/{username}",
        ]
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
        """插件卸载/停用时调用"""
        pass
