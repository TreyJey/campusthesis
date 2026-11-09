// Запросы к API

/* Отправляет запрос к бэкенду и возвращает JSON
При ошибке бросает исключение с текстом из поля detail ответа сервера*/
async function api(path, options = {}) {
    const settings = { method: options.method || "GET", headers: {} };
    if (options.body instanceof FormData) {
        settings.body = options.body;
    } else if (options.body !== undefined) {
        settings.headers["Content-Type"] = "application/json";
        settings.body = JSON.stringify(options.body);   // объект JavaScript в строку JSON
    }

    const response = await fetch(path, settings);
    const data = await response.json().catch(() => null);
    if (!response.ok) {
        let message = "Ошибка сервера";
        if (data && typeof data.detail === "string") {
            message = data.detail;  // HTTPException
        } else if (data && Array.isArray(data.detail)) {
            message = "Проверьте заполнение полей";
        }
        throw new Error(message);
    }
    return data;
}


// Кто вошел
const USER_KEY = "campusthesis_user";

function getUser() {
    const saved = localStorage.getItem(USER_KEY);
    return saved ? JSON.parse(saved) : null;
}

function setUser(user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function logout() {
    localStorage.removeItem(USER_KEY);
    window.location.href = "/index.html";
}

// Пускает на страницу только нужные роли, остальных отправляет на вход
function requireRole(...roles) { // рест параметр, аргументы собираются в массив roles = ["supervisor", "admin"]
    const user = getUser();
    if (!user || (roles.length > 0 && !roles.includes(user.role))) {
        window.location.href = "/index.html";
        return null;
    }
    return user;
}


//Шапка
const ROLE_NAMES = { student: "Студент", supervisor: "Руководитель", admin: "Методист" };// база - отображение

const NAV_LINKS = {
    student: [["catalog.html", "Каталог тем"], ["student.html", "Моя ВКР"]],
    supervisor: [["supervisor.html", "Мои студенты"], ["catalog.html", "Каталог тем"]],
    admin: [["admin.html", "Все ВКР"], ["catalog.html", "Каталог тем"]],
};

async function renderHeader() {
    const user = getUser();
    const header = document.getElementById("app-header");
    if (!user || !header) return;

    const current = window.location.pathname.split("/").pop();
    const links = NAV_LINKS[user.role].map(([href, title]) =>
        `<li class="nav-item"><a class="nav-link ${current === href ? "active" : ""}" href="/${href}">${title}</a></li>`
    ).join("");

    header.innerHTML = `
        <nav class="navbar navbar-expand-md navbar-dark bg-primary mb-4">
            <div class="container">
                <a class="navbar-brand fw-semibold" href="/${NAV_LINKS[user.role][0][0]}">CampusThesis</a>
                <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#main-menu">
                    <span class="navbar-toggler-icon"></span>
                </button>
                <div class="collapse navbar-collapse" id="main-menu">
                    <ul class="navbar-nav me-auto">${links}</ul>
                    <div class="d-flex align-items-center gap-3">
                        <a href="/profile.html#notifications" class="btn btn-outline-light btn-sm position-relative" id="notifications-bell">
                            Уведомления
                            <span class="position-absolute top-0 start-100 translate-middle badge rounded-pill bg-danger d-none"
                                  id="notifications-count"></span>
                        </a>
                        <a href="/profile.html" class="text-white text-decoration-none small">
                            ${escapeHtml(user.full_name)}<br>
                            <span class="opacity-75">${ROLE_NAMES[user.role]}</span>
                        </a>
                        <button class="btn btn-light btn-sm" id="btn-logout">Выйти</button>
                    </div>
                </div>
            </div>
        </nav>`;
    document.getElementById("btn-logout").addEventListener("click", logout);

    // Счётчик непрочитанных уведомлений на кнопке
    try {
        const data = await api(`/api/users/${user.user_id}/notifications?unread_only=true`);
        const badge = document.getElementById("notifications-count");
        if (data.unread_count > 0) {
            badge.textContent = data.unread_count;
            badge.classList.remove("d-none");
        }
    } catch (error) {
        console.error("Не удалось загрузить уведомления:", error.message);
    }
}


// Вспомогательные функции
// Экранирует текст перед вставкой в HTML, чтобы чужой текст не превратился в код, защита от xss
function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text ?? "";
    return div.innerHTML;
}

// "2026-11-20" или "2026-11-20T15:30:00" -> "20.11.2026"
function formatDate(value) {
    if (!value) return "—";
    const [year, month, day] = value.slice(0, 10).split("-");
    return `${day}.${month}.${year}`;
}

// Показывает сообщение в контейнере с алертом
function showMessage(containerId, text, type = "danger") {
    document.getElementById(containerId).innerHTML =
        `<div class="alert alert-${type}">${escapeHtml(text)}</div>`;
}