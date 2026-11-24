const MAIN_API = "http://localhost:8000";
const REPORTS_API = "http://localhost:8001";

let editingId = null;
let expensesCache = {};

function showMessage(text, isError = false) {
  const el = document.getElementById("message");
  el.textContent = text;
  el.className = "message " + (isError ? "error" : "ok");
  clearTimeout(showMessage._timer);
  showMessage._timer = setTimeout(() => {
    el.className = "message hidden";
  }, 4000);
}

function escapeHtml(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDate(date) {
  return escapeHtml(date.split("-").reverse().join("."));
}

function formatMoney(val) {
  return Number(val).toLocaleString("ru-RU", {style: "currency", currency: "RUB"});
}

function showResult(group, visible) {
  document.getElementById(group + "ResultBox").hidden = !visible;
  document.getElementById(group + "Hide").hidden = !visible;
}

function refreshHistory() {
  if (!document.getElementById("historyResultBox").hidden) loadExpenses();
}

function manualPeriod(group) {
  document.getElementById(group + "Period").value = "custom";
}

function choosePeriod(group, period) {
  const from = document.getElementById(group + "From");
  const to = document.getElementById(group + "To");
  if (period === "custom") {
    from.focus();
    return;
  }
  if (period === "all") {
    from.value = "";
    to.value = "";
  } else {
    const today = new Date();
    const end = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()));
    const start = new Date(end);
    if (period === "week") {
      start.setUTCDate(start.getUTCDate() - 6);
    } else {
      // Начало периода — следующий день после границы предыдущего месяца.
      start.setUTCDate(1);
      start.setUTCMonth(start.getUTCMonth() - Number(period) + 1);
      start.setUTCDate(0);
      start.setUTCDate(Math.min(end.getUTCDate(), start.getUTCDate()) + 1);
    }
    from.value = start.toISOString().slice(0, 10);
    to.value = end.toISOString().slice(0, 10);
  }
}

function filters(group) {
  const from = document.getElementById(group + "From").value;
  const to = document.getElementById(group + "To").value;
  const category = document.getElementById(group + "Category").value;
  if (from && to && from > to) throw new Error("Дата начала позже даты окончания");
  const params = new URLSearchParams();
  if (from) params.set("from_date", from);
  if (to) params.set("to_date", to);
  if (category) params.set("category_id", category);
  return params;
}

async function request(url, method = "GET", body) {
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body)
    });
  } catch {
    throw new Error("Не удалось связаться с сервисом");
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : "Проверьте введённые данные");
  }
  return response.json();
}

async function loadCategories() {
  try {
    const data = await request(MAIN_API + "/categories");

    const list = document.getElementById("categoriesList");
    list.innerHTML = "";

    const expSelect = document.getElementById("expCategory");
    const filterSelect = document.getElementById("historyCategory");
    const prevExp = expSelect.value;
    const prevFilter = filterSelect.value;
    const reportSelect = document.getElementById("reportCategory");
    const prevReport = reportSelect.value;

    expSelect.innerHTML = '<option value="" disabled selected>Выберите...</option>';
    filterSelect.innerHTML = '<option value="">Все</option>';

    if (data.length === 0) {
      expSelect.innerHTML = '<option value="" disabled selected>Сначала создайте категорию</option>';
    }

    data.forEach(function (cat) {
      const li = document.createElement("li");
      li.innerHTML =
        "<span>" + escapeHtml(cat.name) + "</span>" +
        '<button class="small secondary" onclick="renameCategory(' + cat.id + ')">Переименовать</button>' +
        '<button class="small danger" onclick="deleteCategory(' + cat.id + ')">Удалить</button>';
      list.appendChild(li);

      const opt1 = document.createElement("option");
      opt1.value = cat.id;
      opt1.textContent = cat.name;
      expSelect.appendChild(opt1);

      const opt2 = document.createElement("option");
      opt2.value = cat.id;
      opt2.textContent = cat.name;
      filterSelect.appendChild(opt2);
    });

    reportSelect.innerHTML = filterSelect.innerHTML;
    reportSelect.value = data.some(cat => String(cat.id) === prevReport) ? prevReport : "";

    if (prevExp && data.some(function (c) { return String(c.id) === String(prevExp); })) {
      expSelect.value = prevExp;
    }
    if (
      (prevFilter && data.some(function (c) { return String(c.id) === String(prevFilter); }))
    ) {
      filterSelect.value = prevFilter;
    }
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function addCategory() {
  const input = document.getElementById("categoryName");
  const name = input.value.trim();
  if (!name) {
    showMessage("Введите название категории", true);
    return;
  }
  try {
    await request(MAIN_API + "/categories", "POST", {name});
    input.value = "";
    showMessage("Категория добавлена");
    loadCategories();
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function renameCategory(id) {
  const name = prompt("Новое название категории", document.querySelector(`#expCategory option[value="${id}"]`).textContent);
  if (name === null) return;
  if (!name.trim() || name.trim().length > 50) {
    showMessage("Введите название от 1 до 50 символов", true);
    return;
  }
  try {
    await request(MAIN_API + "/categories/" + id, "PUT", {name: name.trim()});
    await loadCategories();
    refreshHistory();
    showMessage("Категория переименована");
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function deleteCategory(id) {
  if (!confirm("Удалить категорию?")) return;
  try {
    await request(MAIN_API + "/categories/" + id, "DELETE");
    showMessage("Категория удалена");
    loadCategories();
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function saveExpense() {
  const amount = document.getElementById("expAmount").value;
  const date = document.getElementById("expDate").value;
  const category_id = parseInt(document.getElementById("expCategory").value, 10);
  const description = document.getElementById("expDescription").value.trim();

  if (!amount || amount <= 0) {
    showMessage("Сумма должна быть больше 0", true);
    return;
  }
  if (document.getElementById("expAmount").validity.stepMismatch) {
    showMessage("Введите сумму с точностью до копейки", true);
    return;
  }
  if (!date) {
    showMessage("Укажите дату", true);
    return;
  }
  if (!category_id) {
    showMessage("Выберите категорию", true);
    return;
  }

  try {
    const url = MAIN_API + "/expenses" + (editingId ? "/" + editingId : "");
    await request(url, editingId ? "PUT" : "POST", {amount, date, category_id, description});
    showMessage(editingId ? "Расход обновлён" : "Расход добавлен");
    resetExpense();
    refreshHistory();
  } catch (err) {
    showMessage(err.message, true);
  }
}

function renderExpenses(data) {
  const container = document.getElementById("expensesList");
  container.innerHTML = "";
  expensesCache = {};

  if (!data.length) {
    container.textContent = "По выбранным условиям расходов нет";
    return;
  }

  data.forEach(function (exp) {
    expensesCache[exp.id] = exp;

    const card = document.createElement("div");
    card.className = "expense-item";
    card.id = "expense-" + exp.id;

    const descHtml = exp.description
      ? '<div class="expense-desc">' + escapeHtml(exp.description) + "</div>"
      : "";

    card.innerHTML =
      '<div class="expense-main">' +
        '<div class="expense-meta">' +
          '<span class="category-badge">' + escapeHtml(exp.category_name || "Без категории") + "</span>" +
          "<span>" + formatDate(exp.date) + "</span>" +
        "</div>" +
        descHtml +
      "</div>" +
      '<div class="expense-side">' +
        '<div class="expense-amount">' + formatMoney(exp.amount) + "</div>" +
        '<div class="expense-actions">' +
          '<button class="small secondary" onclick="startEditExpense(' + exp.id + ')">Изменить</button>' +
          '<button class="small danger" onclick="deleteExpense(' + exp.id + ')">Удалить</button>' +
        "</div>" +
      "</div>";

    container.appendChild(card);
  });
}

function startEditExpense(id) {
  const exp = expensesCache[id];
  editingId = id;
  document.getElementById("expAmount").value = exp.amount;
  document.getElementById("expDate").value = exp.date;
  document.getElementById("expCategory").value = exp.category_id;
  document.getElementById("expDescription").value = exp.description;
  document.getElementById("expenseTitle").textContent = "Изменить расход";
  document.getElementById("saveButton").textContent = "Сохранить";
  document.getElementById("cancelButton").hidden = false;
  document.getElementById("expAmount").focus();
}

function resetExpense() {
  editingId = null;
  for (const id of ["expAmount", "expDate", "expCategory", "expDescription"]) {
    document.getElementById(id).value = "";
  }
  document.getElementById("expenseTitle").textContent = "Новый расход";
  document.getElementById("saveButton").textContent = "Добавить расход";
  document.getElementById("cancelButton").hidden = true;
}

async function loadExpenses() {
  try {
    showResult("history", true);
    renderExpenses(await request(MAIN_API + "/expenses?" + filters("history")));
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function deleteExpense(id) {
  if (!confirm("Удалить расход?")) return;
  try {
    await request(MAIN_API + "/expenses/" + id, "DELETE");
    if (editingId === id) resetExpense();
    showMessage("Расход удалён");
    refreshHistory();
  } catch (err) {
    showMessage(err.message, true);
  }
}

async function loadReport() {
  try {
    const categoryName = document.getElementById("reportCategory").selectedOptions[0].textContent;
    const data = await request(REPORTS_API + "/report?" + filters("report"));
    const box = document.getElementById("reportResult");
    const total = Number(data.total_amount || 0);

    let periodLabel = "За всё время";
    if (data.from_date && data.to_date) {
      periodLabel = "Период: " + formatDate(data.from_date) + " — " + formatDate(data.to_date);
    } else if (data.from_date) {
      periodLabel = "С " + formatDate(data.from_date);
    } else if (data.to_date) {
      periodLabel = "По " + formatDate(data.to_date);
    }

    let html =
      '<div class="report-summary-card">' +
        '<span class="report-summary-label">' + periodLabel + " · " + escapeHtml(categoryName) + "</span>" +
        '<span class="report-summary-total">' + formatMoney(total) + "</span>" +
      "</div>";

    if (data.by_category && data.by_category.length > 0) {
      html += '<div class="report-categories">';
      data.by_category.forEach(function (item) {
        const catTotal = Number(item.total || 0);
        const share = total > 0 ? Math.round((catTotal / total) * 100) : 0;
        const barWidth = total > 0 ? Math.min(100, (catTotal / total) * 100) : 0;

        html +=
          '<div class="report-cat-card">' +
            '<div class="report-cat-header">' +
              '<span class="report-cat-name">' + escapeHtml(item.category_name) + "</span>" +
              '<span class="report-cat-value">' +
                formatMoney(catTotal) +
                '<span class="report-cat-share">(' + share + "%)</span>" +
              "</span>" +
            "</div>" +
            '<div class="progress-track">' +
              '<div class="progress-fill" style="width: ' + barWidth.toFixed(1) + '%"></div>' +
            "</div>" +
          "</div>";
      });
      html += "</div>";
    }

    box.innerHTML = html;
    showResult("report", true);
  } catch (err) {
    showMessage(err.message, true);
  }
}

document.addEventListener("DOMContentLoaded", function () {
  loadCategories();
});
