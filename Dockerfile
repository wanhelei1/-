FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY app.py follow_up_module.py marketing_content_module.py pricing_module.py store_growth_workflow.py index.html ./
COPY 3号(1)/mock_retriever.py 3号(1)/recommendation_engine.py 3号(1)/retrieval_adapter.py /app/3号(1)/
COPY BLOCK-07/block07_compliance.py /app/BLOCK-07/block07_compliance.py
COPY customer_insight_agent/kb_agent.py /app/customer_insight_agent/kb_agent.py
COPY knowledge-base/ ./knowledge-base/
EXPOSE 7860
CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "7860"]
