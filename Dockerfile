FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir -e .

ENV MCP_TRANSPORT=streamable-http
ENV MCP_SERVER_PORT=3000
ENV MCP_HOST=0.0.0.0

EXPOSE 3000

CMD ["python", "-m", "radarr_sonarr_mcp.server", "--transport", "streamable-http"]
