FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://packagefeedproxy.microsoft.io/pypi/simple -r requirements.txt
COPY main.py responses_host.py activity_bridge.py astronomy_tool.py artifact_storage.py teams_widgets.py zodiaque_tropical.py zodiaque_tropical_3d.py zodiac_constellations.json zodiac_constellations.LICENSE.txt zodiaque_tropical_babylon.template.html ./
COPY webchat/client/widget/widget.html webchat/client/widget/widget.html
# Foundry's persistent /home/session mount requires the default container UID.
USER 0
ENV MPLBACKEND=Agg AGENT_HOST=0.0.0.0
EXPOSE 8088
CMD ["python", "main.py"]
