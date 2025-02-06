# 使用官方 Python 镜像作为基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 复制项目文件到容器中
COPY . .

# 安装依赖
RUN pip install --no-cache-dir -r requirements.txt

# 暴露端口 (根据你的应用配置)
EXPOSE 3000

# 设置环境变量 (可选，如果使用 .env 文件)
# ENV KeyArray=""
# ENV MaxRetries=3
# ENV MaxRequests=2
# ENV LimitWindow=60
# ENV password=""
# ENV PORT=3000

# 运行命令
CMD ["flask", "run", "--host=0.0.0.0", "--port=3000"]