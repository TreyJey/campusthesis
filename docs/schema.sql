-- CampusThesis — схема базы данных (14 сущностей)

-- Справочники

CREATE TABLE roles (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(20) NOT NULL UNIQUE          -- student / supervisor
);

CREATE TABLE departments (
    id   SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL UNIQUE         -- кафедра
);

CREATE TABLE directions (
    id            SERIAL PRIMARY KEY,
    code          VARCHAR(20)  NOT NULL UNIQUE,   -- 09.03.03
    name          VARCHAR(200) NOT NULL,          -- Прикладная информатика
    department_id INTEGER NOT NULL REFERENCES departments(id)
);

CREATE TABLE stage_types (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(100) NOT NULL,       -- План, Первая глава, ...
    order_num    INTEGER NOT NULL UNIQUE,     -- порядок этапа: 1..7
    default_days INTEGER NOT NULL             -- сколько дней даётся на этап
);

-- Пользователи

CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    login         VARCHAR(50)  NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    full_name     VARCHAR(200) NOT NULL,
    email         VARCHAR(200),
    role_id       INTEGER NOT NULL REFERENCES roles(id),
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE student_profiles (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL UNIQUE REFERENCES users(id),
    direction_id INTEGER NOT NULL REFERENCES directions(id),
    group_name   VARCHAR(30) NOT NULL,
    course       INTEGER NOT NULL
);

CREATE TABLE supervisor_profiles (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL UNIQUE REFERENCES users(id),
    department_id INTEGER NOT NULL REFERENCES departments(id),
    position      VARCHAR(100) NOT NULL,      -- доцент, профессор
    max_students  INTEGER NOT NULL DEFAULT 5
);

-- Темы и заявки

CREATE TABLE topics (
    id            SERIAL PRIMARY KEY,
    title         VARCHAR(300) NOT NULL,
    description   TEXT NOT NULL,
    requirements  TEXT,
    supervisor_id INTEGER NOT NULL REFERENCES supervisor_profiles(id),
    direction_id  INTEGER NOT NULL REFERENCES directions(id),
    is_available  BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE topic_requests (
    id                 SERIAL PRIMARY KEY,
    topic_id           INTEGER NOT NULL REFERENCES topics(id),
    student_id         INTEGER NOT NULL REFERENCES student_profiles(id),
    message            TEXT, -- сопроводительное сообщение студента
    status             VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending / approved / rejected
    supervisor_comment TEXT,
    created_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    decided_at         TIMESTAMP
);

-- ВКР и этапы

CREATE TABLE theses (
    id            SERIAL PRIMARY KEY,
    student_id    INTEGER NOT NULL UNIQUE REFERENCES student_profiles(id),
    topic_id      INTEGER NOT NULL UNIQUE REFERENCES topics(id),
    supervisor_id INTEGER NOT NULL REFERENCES supervisor_profiles(id),
    status        VARCHAR(20) NOT NULL DEFAULT 'in_progress', -- in_progress / defended
    created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE thesis_stages (
    id            SERIAL PRIMARY KEY,
    thesis_id     INTEGER NOT NULL REFERENCES theses(id),
    stage_type_id INTEGER NOT NULL REFERENCES stage_types(id),
    deadline      DATE NOT NULL,
    status        VARCHAR(20) NOT NULL DEFAULT 'locked', -- locked / open / submitted / revision / approved
    submitted_at  TIMESTAMP,
    approved_at   TIMESTAMP
);

CREATE TABLE stage_files (
    id              SERIAL PRIMARY KEY,
    thesis_stage_id INTEGER NOT NULL REFERENCES thesis_stages(id),
    uploaded_by     INTEGER NOT NULL REFERENCES users(id),
    original_name   VARCHAR(255) NOT NULL,
    stored_path     VARCHAR(500) NOT NULL,
    size_bytes      INTEGER NOT NULL,
    uploaded_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE reviews (
    id              SERIAL PRIMARY KEY,
    thesis_stage_id INTEGER NOT NULL REFERENCES thesis_stages(id),
    supervisor_id   INTEGER NOT NULL REFERENCES supervisor_profiles(id),
    decision        VARCHAR(20) NOT NULL, -- approved / revision
    comment         TEXT,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Уведомления

CREATE TABLE notifications (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    type       VARCHAR(30) NOT NULL, -- deadline / comment / status
    text       VARCHAR(500) NOT NULL,
    link       VARCHAR(300), -- куда ведёт клик по уведомлению
    is_read    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
