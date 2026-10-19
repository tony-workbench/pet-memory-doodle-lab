# Pet Memory Doodle Lab

把一段与宠物相处的小事，变成一张稀疏的黑白圆珠笔涂鸦。中文网页，本地运行，Python 标准库后端，无需安装第三方依赖。

![第二轮 prompt 的实际生成示例](static/assets/sample-dog-walk.png)

## 本地运行

需要 Python 3.9 或更新版本：

```sh
python3 app.py
```

在 Safari 或其他浏览器打开 <http://127.0.0.1:8767>。不配置密钥也能编辑画面、预览完整 prompt、复制或下载 prompt，以及查看和下载示例图。

要生成新图片，在运行程序的终端设置 `OPENAI_API_KEY` 环境变量，再启动程序。密钥应来自你自己的 OpenAI API 账户；不要填在网页、代码、截图或 Git 提交里。程序不读取 `.env` 文件。可用以下方式在 macOS 的 zsh 中隐藏输入，并避免将密钥写入 shell 历史：

```sh
read -rs 'OPENAI_API_KEY?OpenAI API key: '
export OPENAI_API_KEY
python3 app.py
```

用完按 `Ctrl+C` 停止服务，再运行 `unset OPENAI_API_KEY`。默认仅监听本机 `127.0.0.1`。如端口被占用，可用 `python3 app.py --port 8768` 并打开对应地址。

## 怎样使用

1. 选择场景示例，或填写一段具体的画面动作。可用中文或英文；这一步直接使用你输入的描述，不会先调用另一个模型改写日记。
2. 写清画面里只保留哪些物件。查看完整 prompt，确认没有需要删除的个人信息。
3. 配置密钥后点击“生成”。只有这一步会把组合后的 prompt 发给 OpenAI，并可能产生 API 费用。
4. 下载 PNG。网页不会把日记或生成图写入本地数据库；刷新后不保留编辑内容。

## 第二轮 prompt

`prompts/reference-v2.txt` 保留了选中的第二轮英文 prompt。默认场景构建出的 prompt 与该文件完全一致。核心约束为正方形画面、统一细黑线、白底、极少笔画，只保留主体和指定物件，不画背景、阴影或毛发纹理。修改场景时沿用这些约束。

示例 PNG 是此前使用该 prompt 生成并挑选的图片，不是程序根据当前输入实时生成的结果。图片生成具有随机性；换模型或再次生成，不保证得到相同构图。

这个项目是一个独立实验工具，未与 Lifelog 官方关联。它延续第二轮 prompt 的视觉实验，不包含原应用安装包、原应用图片库、账号数据或后端凭据，也不声称复刻了原应用的服务端实现。

## API 与实现

后端固定调用 `https://api.openai.com/v1/images/generations`，使用 `gpt-image-2.5-flare`，每次请求 1 张 1024×1024、high 质量、白色不透明背景的 PNG；网页不能覆盖目标地址或模型。参数和返回格式参照 [OpenAI 官方图像 API 文档](https://developers.openai.com/api/reference/resources/images/methods/generate)。实际可用性取决于你的账户权限和余额。

- `GET /api/config`：模型、是否配置密钥、本地会话防伪令牌与默认输入。
- `POST /api/prompt`：仅在本机组合 prompt。
- `POST /api/generate`：显式请求生成新图。

所有 POST 请求都校验同源请求与本地会话令牌。密钥只留在服务端进程；程序不输出密钥、日记、请求头或第三方错误正文。代码不包含分析脚本、远程字体或第三方前端依赖。

## 验证与适用范围

```sh
python3 -m unittest discover -s tests -v
```

测试覆盖 prompt 一致性、本地 HTTP 边界、恶意输入、错误处理和模拟的图像 API 响应。模拟测试不等同于真实付费 API 调用；交付时未配置 API 密钥，因此真实新图生成尚未在这个独立工具内验证。

这是单人本地原型。请勿把它改成监听公网后直接作为多用户服务；线上产品还需要身份验证、配额、存储与部署设计。安全检查范围与结果见 [SECURITY.md](SECURITY.md)。
