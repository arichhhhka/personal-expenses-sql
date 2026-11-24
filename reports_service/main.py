# Сервис отчётов
# Порт: 8001
# Сам базу не трогает — берёт данные из основного сервиса по HTTP

from typing import Optional, List, Dict
from datetime import date
from decimal import Decimal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

# Адрес основного сервиса внутри Docker-сети
# (имя сервиса из docker-compose.yml)
MAIN_SERVICE_URL = "http://main_service:8000"

app = FastAPI(
    title="Сервис отчётов",
    description="Считает общую сумму и суммы по категориям за период",
    version="1.0",
)

# Разрешаем запросы с фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Модели ответа ----------

class CategorySum(BaseModel):
    category_id: int
    category_name: str
    total: float


class ReportResponse(BaseModel):
    from_date: Optional[date]
    to_date: Optional[date]
    total_amount: float
    by_category: List[CategorySum]


# ЭНДПОИНТ ОТЧЁТА

@app.get("/report", response_model=ReportResponse)
def get_report(
    from_date: Optional[date] = Query(None, description="Начало периода"),
    to_date: Optional[date] = Query(None, description="Конец периода"),
    category_id: Optional[int] = Query(None, description="Только одна категория"),
):
    """
    Получает расходы из основного сервиса и считает:
    - общую сумму
    - суммы по каждой категории
    """

    # Собираем параметры запроса к основному сервису
    if from_date and to_date and from_date > to_date:
        raise HTTPException(400, "Дата начала позже даты окончания")
    params = {}
    if from_date is not None:
        params["from_date"] = from_date.isoformat()
    if to_date is not None:
        params["to_date"] = to_date.isoformat()
    if category_id is not None:
        params["category_id"] = category_id

    # Делаем HTTP-запрос к основному сервису
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(f"{MAIN_SERVICE_URL}/expenses", params=params)
            response.raise_for_status()
            expenses = response.json()
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Не удалось связаться с основным сервисом: {e}"
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Основной сервис вернул ошибку: {e.response.status_code}"
        )

    # Считаем общую сумму
    total_kopecks = 0
    # Словарь: category_id → {name, total}
    categories: Dict[int, dict] = {}

    for exp in expenses:
        kopecks = int(Decimal(str(exp["amount"])) * 100)
        total_kopecks += kopecks

        cat_id = exp["category_id"]
        cat_name = exp.get("category_name", "Без названия")

        if cat_id not in categories:
            categories[cat_id] = {
                "category_id": cat_id,
                "category_name": cat_name,
                "kopecks": 0,
            }
        categories[cat_id]["kopecks"] += kopecks

    # Превращаем словарь в список
    by_category = [
        CategorySum(
            category_id=item["category_id"],
            category_name=item["category_name"],
            total=item["kopecks"] / 100,
        )
        for item in categories.values()
    ]

    # Сортируем по сумме (от большей к меньшей)
    by_category.sort(key=lambda x: x.total, reverse=True)

    return ReportResponse(
        from_date=from_date,
        to_date=to_date,
        total_amount=total_kopecks / 100,
        by_category=by_category,
    )


@app.get("/health")
def health():
    """Простая проверка, что сервис жив"""
    return {"status": "ok"}
