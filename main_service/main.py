# Основной сервис учёта личных расходов
# Порт: 8000

from pathlib import Path
from typing import List, Optional
import datetime
from decimal import Decimal
from sqlalchemy.exc import IntegrityError
from sqlalchemy import event
from database import prepare_database

from fastapi import FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import create_engine, Column, Integer, String, CheckConstraint, Date, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# Папка data будет рядом с этим файлом
DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)

# Файл базы SQLite
DATABASE_URL = f"sqlite:///{(DATA_DIR / 'expenses.db').as_posix()}"

# Создаём подключение к базе
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}  # нужно для SQLite
)

# Фабрика сессий
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

# Базовый класс для моделей таблиц
Base = declarative_base()


class CategoryDB(Base):
    """Таблица категорий"""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)

    # Связь: одна категория → много расходов
    expenses = relationship("ExpenseDB", back_populates="category")


class ExpenseDB(Base):
    """Таблица расходов"""
    __tablename__ = "expenses"

    id = Column(Integer, primary_key=True, index=True)
    amount_kopecks = Column(Integer, nullable=False)
    __table_args__ = (CheckConstraint("amount_kopecks > 0"),)
    date = Column(Date, nullable=False)             # дата расхода
    description = Column(String(200), default="")   # комментарий
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False)

    # Связь: расход принадлежит одной категории
    category = relationship("CategoryDB", back_populates="expenses")


# Создаём таблицы, если их ещё нет
@event.listens_for(engine, "connect")
def enable_foreign_keys(connection, record):
    connection.execute("PRAGMA foreign_keys = ON")


prepare_database(DATA_DIR / "expenses.db")
Base.metadata.create_all(bind=engine)

# Сумма в рублях для просмотра таблицы. SQLite сама обновляет её при изменении расхода.
with engine.begin() as connection:
    columns = connection.exec_driver_sql("PRAGMA table_xinfo(expenses)").mappings()
    if "amount_rubles" not in [column["name"] for column in columns]:
        connection.exec_driver_sql("""
            ALTER TABLE expenses ADD COLUMN amount_rubles TEXT GENERATED ALWAYS AS
            (printf('%d,%02d ₽', amount_kopecks / 100, amount_kopecks % 100)) VIRTUAL
        """)


class CategoryInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(..., min_length=1, max_length=50)


class CategoryResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class ExpenseCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, max_digits=14, decimal_places=2, description="Сумма должна быть больше 0")
    date: datetime.date
    description: str = Field("", max_length=200)
    category_id: int


class ExpenseUpdate(BaseModel):
    amount: Optional[Decimal] = Field(None, gt=0, max_digits=14, decimal_places=2)
    date: Optional[datetime.date] = None
    description: Optional[str] = Field(None, max_length=200)
    category_id: Optional[int] = None


class ExpenseResponse(BaseModel):
    id: int
    amount: float
    date: datetime.date
    description: str
    category_id: int
    category_name: str = ""   # удобно сразу видеть название категории

    model_config = ConfigDict(from_attributes=True)


app = FastAPI(
    title="Основной сервис учёта расходов",
    description="Курсовая работа. CRUD для категорий и расходов.",
    version="1.0",
)

# Разрешаем запросы с фронтенда (чтобы не было ошибки CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ЭНДПОИНТЫ ДЛЯ КАТЕГОРИЙ

@app.exception_handler(RequestValidationError)
async def validation_error(request, error):
    field = error.errors()[0]["loc"][-1]
    messages = {
        "amount": "Введите положительную сумму в рублях, не более двух знаков после запятой и до 12 цифр до запятой",
        "description": "Комментарий — не более 200 символов",
        "name": "Введите название от 1 до 50 символов",
        "date": "Укажите дату расхода",
        "category_id": "Укажите номер категории",
        "from_date": "Проверьте дату начала периода",
        "to_date": "Проверьте дату окончания периода",
    }
    return JSONResponse(status_code=422, content={"detail": messages.get(field, "Проверьте параметры запроса")})


def save_category(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        db.close()
        raise HTTPException(400, "Категория с таким именем уже существует")


@app.get("/categories", response_model=List[CategoryResponse])
def get_categories():
    """Получить все категории"""
    db = SessionLocal()
    categories = db.query(CategoryDB).order_by(CategoryDB.id).all()
    db.close()
    return categories


@app.post("/categories", response_model=CategoryResponse, status_code=201)
def create_category(category: CategoryInput):
    """Создать новую категорию"""
    db = SessionLocal()

    new_cat = CategoryDB(name=category.name)
    db.add(new_cat)
    save_category(db)
    db.refresh(new_cat)
    db.close()
    return new_cat


@app.put("/categories/{category_id}", response_model=CategoryResponse)
def update_category(category_id: int, category: CategoryInput):
    """Изменить название категории"""
    db = SessionLocal()
    cat = db.query(CategoryDB).filter(CategoryDB.id == category_id).first()

    if not cat:
        db.close()
        raise HTTPException(status_code=404, detail="Категория не найдена")

    cat.name = category.name
    save_category(db)
    db.refresh(cat)
    db.close()
    return cat


@app.delete("/categories/{category_id}")
def delete_category(category_id: int):
    """Удалить категорию (только если у неё нет расходов)"""
    db = SessionLocal()
    cat = db.query(CategoryDB).filter(CategoryDB.id == category_id).first()

    if not cat:
        db.close()
        raise HTTPException(status_code=404, detail="Категория не найдена")

    # Проверяем, есть ли расходы в этой категории
    has_expenses = db.query(ExpenseDB).filter(ExpenseDB.category_id == category_id).first()
    if has_expenses:
        db.close()
        raise HTTPException(
            status_code=400,
            detail="Нельзя удалить категорию, у которой есть расходы"
        )

    db.delete(cat)
    db.commit()
    db.close()
    return {"detail": "Категория удалена"}


# ЭНДПОИНТЫ ДЛЯ РАСХОДОВ

@app.get("/expenses", response_model=List[ExpenseResponse])
def get_expenses(
    from_date: Optional[datetime.date] = Query(None, description="Начало периода"),
    to_date: Optional[datetime.date] = Query(None, description="Конец периода"),
    category_id: Optional[int] = Query(None, description="Фильтр по категории"),
):
    """
    Получить расходы.
    Можно фильтровать по дате (from_date, to_date) и по category_id.
    """
    if from_date and to_date and from_date > to_date:
        raise HTTPException(400, "Дата начала позже даты окончания")
    db = SessionLocal()
    query = db.query(ExpenseDB)

    # Фильтр по дате начала
    if from_date is not None:
        query = query.filter(ExpenseDB.date >= from_date)

    # Фильтр по дате конца
    if to_date is not None:
        query = query.filter(ExpenseDB.date <= to_date)

    # Фильтр по категории
    if category_id is not None:
        query = query.filter(ExpenseDB.category_id == category_id)

    expenses = query.order_by(ExpenseDB.date.desc()).all()

    # Собираем ответ с названием категории
    result = []
    for exp in expenses:
        result.append(ExpenseResponse(
            id=exp.id,
            amount=exp.amount_kopecks / 100,
            date=exp.date,
            description=exp.description or "",
            category_id=exp.category_id,
            category_name=exp.category.name if exp.category else "",
        ))

    db.close()
    return result


@app.post("/expenses", response_model=ExpenseResponse, status_code=201)
def create_expense(expense: ExpenseCreate):
    """Добавить новый расход"""
    db = SessionLocal()

    # Проверяем, что категория существует
    cat = db.query(CategoryDB).filter(CategoryDB.id == expense.category_id).first()
    if not cat:
        db.close()
        raise HTTPException(status_code=400, detail="Категория не найдена")

    new_exp = ExpenseDB(
        amount_kopecks=int(expense.amount * 100),
        date=expense.date,
        description=expense.description or "",
        category_id=expense.category_id,
    )
    db.add(new_exp)
    db.commit()
    db.refresh(new_exp)

    response = ExpenseResponse(
        id=new_exp.id,
        amount=new_exp.amount_kopecks / 100,
        date=new_exp.date,
        description=new_exp.description,
        category_id=new_exp.category_id,
        category_name=cat.name,
    )
    db.close()
    return response


@app.put("/expenses/{expense_id}", response_model=ExpenseResponse)
def update_expense(expense_id: int, expense: ExpenseUpdate):
    """Изменить расход (можно передать только нужные поля)"""
    db = SessionLocal()
    exp = db.query(ExpenseDB).filter(ExpenseDB.id == expense_id).first()

    if not exp:
        db.close()
        raise HTTPException(status_code=404, detail="Расход не найден")

    # Обновляем только те поля, которые передали
    if expense.amount is not None:
        exp.amount_kopecks = int(expense.amount * 100)
    if expense.date is not None:
        exp.date = expense.date
    if expense.description is not None:
        exp.description = expense.description
    if expense.category_id is not None:
        # Проверяем категорию
        cat = db.query(CategoryDB).filter(CategoryDB.id == expense.category_id).first()
        if not cat:
            db.close()
            raise HTTPException(status_code=400, detail="Категория не найдена")
        exp.category_id = expense.category_id

    db.commit()
    db.refresh(exp)

    response = ExpenseResponse(
        id=exp.id,
        amount=exp.amount_kopecks / 100,
        date=exp.date,
        description=exp.description or "",
        category_id=exp.category_id,
        category_name=exp.category.name if exp.category else "",
    )
    db.close()
    return response


@app.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int):
    """Удалить один расход"""
    db = SessionLocal()
    exp = db.query(ExpenseDB).filter(ExpenseDB.id == expense_id).first()

    if not exp:
        db.close()
        raise HTTPException(status_code=404, detail="Расход не найден")

    db.delete(exp)
    db.commit()
    db.close()
    return {"detail": "Расход удалён"}
