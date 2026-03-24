# X账号评分 - AstrBot 插件

查询 X(Twitter) 账号可信度评分，基于 [flj.info](https://flj.info) 的 AI 分析。

## 功能

- 输入 X 用户名，自动调用 flj.info API 进行可信度分析
- 生成包含评分、标签、评分明细、AI 评价、近期媒体、用户评论的图片报告
- 支持自动撤回（可配置延迟）
- 图片生成失败时自动回退为纯文本

## 使用方法

```
/X账号评分 <用户名>
```

示例：

```
/X账号评分 elonmusk
```

## 配置项

| 配置项 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `recall_delay` | int | 0 | 发送评分图片后多少秒自动撤回，0 表示不撤回 |
| `show_analyze_alert` | bool | true | 是否在分析时发送"正在分析..."提示 |

## 字体

插件会自动查找系统中文字体。如果需要使用自定义字体，将 `.ttf` / `.ttc` / `.otf` 文件放到插件目录下即可自动识别。

## 依赖

- `aiohttp` - 网络请求
- `Pillow` - 图片生成

## 文件说明

```
├── main.py             # 插件入口，指令处理与消息发送
├── image_render.py     # 图片渲染模块，生成可信度报告图片
├── metadata.yaml       # 插件元数据
├── _conf_schema.json   # 配置项定义
└── requirements.txt    # Python 依赖
```
