

# Gemini Proxy

[![GitHub license](https://img.shields.io/github/license/HerSophia/Gemini-rProxy)](https://github.com/HerSophia/Gemini-rProxy/blob/master/LICENSE)  <!-- 替换成你的 License -->

## 简介

本项目是一个 Google Gemini 模型的代理服务，基于 Flask 框架构建。绝大部分工作源于[@Moonfanzp](https://github.com/Moonfanz)，本人只是基于此提供了一个不止于docker的方案，做了点小小的工作。它提供了以下主要功能：

*   **OpenAI API 兼容性：** 实现了 OpenAI Chat Completions API (`/v1/chat/completions`) 和 Models API (`/v1/models`)，方便与现有工具和库集成。
*   **多 API 密钥管理：** 支持配置多个 Google API 密钥，自动轮换和禁用超限密钥，提高可用性。
*   **速率限制：** 内置请求速率限制，防止单个 API 密钥超额使用。
*   **自动重试：** 遇到 Google API 错误时自动重试，增强稳定性。
*   **流式输出：** 支持流式响应 (streaming)，提供更快的响应速度。
*   **安全设置：** 可配置 Gemini 模型的安全设置（当前版本默认关闭了所有安全过滤）。
*   **系统代理支持：** 自动检测并使用系统代理设置，或通过环境变量手动配置代理。
*   **跨平台：** 可作为 Python 脚本直接运行，在众多云服务器或本地环境进行使用，也可打包成独立的 .exe 文件（Windows）。
*   **易于配置：** 通过 `env.json` 或 `.env` 文件进行配置。

## 快速开始

### 1. 准备工作

*   **Python 环境：**  需要 Python 3.7 或更高版本。
*   **Google API 密钥：**  需要一个或多个有效的 Google API 密钥。

### 2. 获取代码

```bash
git clone https://github.com/HerSophia/Gemini-rProxy
```

### 3. 安装依赖

```bash
cd Gemini-rProxy
pip install -r requirements.txt
```

### 4. 配置

在项目根目录下创建 `env.json` 或 `.env` 文件，并设置以下环境变量：

**`env.json` 示例：**

```json
{
  "KeyArray": "AIzaSy...\nAIzaSy...\nAIzaSy...",  
  "MaxRetries": 3,            
  "MaxRequests": 2,           
  "LimitWindow": 60,          
  "password": "your_password", 
  "PORT": 3000,               
  "http_proxy": "http://your_proxy:port", 
  "https_proxy": "https://your_proxy:port" 
}
```

**`.env` 示例：**

```
KeyArray=AIzaSy...\nAIzaSy...\nAIzaSy...
MaxRetries=3
MaxRequests=2
LimitWindow=60
password=your_password
PORT=3000
http_proxy=http://your_proxy:port
https_proxy=https://your_proxy:port
```

**说明：**

*   `KeyArray`:  **必需。** 你的 Google API 密钥列表。多个密钥可以换行分隔，也可以用空格分隔（但建议换行）。
*   `MaxRetries`:  可选。请求失败时的最大重试次数。
*   `MaxRequests`:  可选。每个 API 密钥在 `LimitWindow` 时间内的最大请求次数。
*   `LimitWindow`:  可选。速率限制窗口大小（秒）。
*   `password`:  **必需。** 用于 API 认证的密码。客户端请求时需要在 `Authorization` 请求头中提供，格式为 `Bearer your_password`。
*   `PORT`:  可选。Flask 应用监听的端口。
*   `http_proxy` / `https_proxy`:  可选。HTTP 和 HTTPS 代理设置。如果未设置，程序会自动检测系统代理。

### 4. 运行

**作为 Python 脚本运行：**

```bash
python app.py
```

**作为 .exe 文件运行 (Windows)：**

1.  **打包：**

    ```bash
    pip install pyinstaller
    pyinstaller --onefile --name gemini-proxy --add-data="func.py;." app.py
    ```

2.  **运行：**  将 `env.json` 或 `.env` 文件复制到 `dist` 目录下，与 `gemini-proxy.exe` 放在一起，然后双击运行 `gemini-proxy.exe`。

### 注意

*   根目录下的`./dist`文件夹中以打包好.exe文件，可直接使用，同样要注意`env.json` 或 `.env` 文件和.exe文件存在同一个文件夹中

### 5. 测试

*   **访问测试页面：** 在浏览器中打开 `http://127.0.0.1:3000/` (如果使用了默认端口)。
*   **发送 API 请求：** 使用 curl、Postman 或其他工具向 `/hf/v1/chat/completions` 发送 POST 请求，测试 API 是否正常工作。记得在请求头中添加 `Authorization: Bearer your_password`。

### 6. API 参考

*   `/hf/v1/chat/completions`:   OpenAI Chat Completions API。
*   `/hf/v1/models`:  列出支持的 Gemini 模型。

请求和响应格式与 OpenAI API 基本兼容，但请注意，本项目是 Gemini 模型的代理，而不是 OpenAI 服务的代理。

### Docker 方式（可选）
1.  **构建镜像：**

    ```bash
    docker-compose build
    ```

2.  **运行容器：**

    ```bash
    docker-compose up
    ```
    首次运行，可以使用
    ```bash
     docker-compose up --build
    ```
    注意，你可能需要配置.env文件，或者使用
    ```
    KeyArray="AIzaSy..." password="your_password" docker-compose up --build
    ```
    来运行。

## 高级配置

*   **安全设置：**  当前版本的代码中，安全设置被硬编码为全部禁用 (`BLOCK_NONE`)。如果需要修改安全设置，请直接编辑 `app.py` 文件中的 `safety_settings` 变量。
*   **Keep-Alive:**  代码中包含一个 `keep_alive()` 函数，定期向本地地址发送请求，以保持应用活跃。如果你不需要这个功能，可以注释掉相关代码。

## 注意事项

*   **API 密钥安全：**  请妥善保管你的 Google API 密钥，不要将其泄露给他人。
*   **速率限制：**  Google Gemini API 有速率限制。请根据你的 API 密钥配额和应用需求，合理配置 `MaxRequests` 和 `LimitWindow`。
* **代理**：如果你的网络环境需要通过代理才能访问 Google API, 请务必设置 `http_proxy` 和 `https_proxy` 环境变量，或者确保系统代理设置正确。虽然代码中写了自动获取代理端口并进行自动使用，但以防万一，还是写好环境变量为好。

## 免责声明

本项目仅供学习和研究使用，不保证其稳定性、可靠性和安全性。请在使用前仔细阅读 Google Gemini API 的使用条款，并遵守相关规定。

## 贡献

欢迎提交 Issue 或 Pull Request。

## License

[MIT](LICENSE)  <!-- 替换成你的 License -->
