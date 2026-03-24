# Slack 사내 지식 검색 봇

Slack DM으로 질문하면 Gmail과 Google Drive를 검색해 Gemini가 요약 답변을 돌려주는 봇입니다.

---

## Overview

사용자가 Slack에서 봇에게 DM을 보내면, 해당 질문에서 핵심 키워드를 추출해 Gmail과 Google Drive를 검색한 뒤 Gemini 2.5 Flash가 결과를 요약해서 응답합니다. 처음 사용하는 사람에게는 Google OAuth 연동 버튼을 자동으로 발송합니다.

---

## 주요 기능

- **Slack DM 수신**: 봇에게 DM을 보내면 자동으로 처리
- **Google OAuth 연동**: 미연동 사용자에게 인증 버튼 자동 발송, CSRF 방어용 state 검증 포함
- **Gmail 검색**: 사용자의 Gmail에서 키워드로 메일 검색 (최대 10건), 제목/발신자/요약 추출
- **Google Drive 검색**: Drive 파일 전문 검색 (최대 10건), 파일명/수정일/링크 추출
- **Gemini 키워드 추출**: 자연어 질문에서 검색 키워드를 Gemini로 추출
- **Gemini 요약 답변**: 검색 결과를 바탕으로 한국어 요약 생성
- **토큰 자동 갱신**: Google access token 만료 5분 전 자동 refresh
- **토큰 암호화 저장**: Fernet 대칭키로 access/refresh token DB 암호화

---

## 동작 방식

```
┌─────────────────────────────────────────────────────────────┐
│                        Slack                                │
│                                                             │
│   사용자 ──DM 전송──▶ 봇                                    │
│                        │                                   │
└────────────────────────│────────────────────────────────────┘
                         │
                         ▼
              ┌─────────────────────┐
              │  DB 유저 조회        │
              │  (slack_user_id)    │
              └──────────┬──────────┘
                         │
             ┌───────────┴───────────┐
             │                       │
          미연동                   연동됨
             │                       │
             ▼                       ▼
  ┌──────────────────┐    ┌──────────────────────┐
  │ OAuth 버튼 발송   │    │ Gemini: 키워드 추출   │
  │                  │    │ "건강검진 메일 요약"   │
  │  [Google 로그인] │    │  → "건강검진"         │
  └──────────────────┘    └──────────┬───────────┘
           │                         │
           │ 클릭                     ▼
           ▼              ┌──────────────────────┐
  ┌────────────────┐      │  Gmail API 검색       │
  │ Google OAuth   │      │  Drive API 검색       │
  │ /auth/google/  │      │  (최대 각 10건)        │
  │ callback       │      └──────────┬───────────┘
  │                │                 │
  │ 토큰 암호화 후 │                 ▼
  │ DB 저장        │      ┌──────────────────────┐
  └────────────────┘      │ Gemini 2.5 Flash     │
                          │ 검색 결과 요약        │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │  Slack DM으로 답변    │
                          └──────────────────────┘
```

1. 봇이 DM을 수신하면 DB에서 해당 Slack 유저를 조회합니다.
2. 미연동 유저에게는 Google OAuth 버튼을 보냅니다. 버튼 클릭 시 `/auth/google/callback`으로 리다이렉트돼 토큰을 암호화(Fernet)하여 DB에 저장합니다.
3. 연동된 유저의 질문은 Gemini가 핵심 키워드로 변환한 뒤 Gmail API와 Drive API로 검색합니다.
4. 검색 결과를 Gemini에 전달해 한국어 요약을 생성하고 DM으로 응답합니다.

---

## 기술 스택

| 분류          | 라이브러리 / 서비스                            |
| ------------- | ---------------------------------------------- |
| 웹 프레임워크 | FastAPI 0.115, Uvicorn 0.30                    |
| Slack         | slack-bolt 1.21 (Socket Mode)                  |
| Google API    | google-api-python-client, google-auth-oauthlib |
| AI            | google-genai (Gemini 2.5 Flash)                |
| DB            | PostgreSQL + SQLAlchemy 2.0 (asyncpg)          |
| 마이그레이션  | Alembic 1.14                                   |
| 암호화        | cryptography (Fernet)                          |
| 설정          | pydantic-settings                              |
| 배포          | Railway                                        |

---

## Slack App 생성 가이드

서버를 실행하기 전에 Slack App을 먼저 만들어야 합니다. 서버 실행만으로 슬랙봇이 자동 생성되지 않습니다.

### 1. 앱 생성

1. [api.slack.com/apps](https://api.slack.com/apps) 접속 (회사 Slack 계정으로 로그인)
2. **Create New App** → **From scratch** 선택
3. App Name 입력 (예: `KnowledgeBot`), 워크스페이스 선택 → **Create App**

### 2. App Home 설정 (Bot User 생성)

> ⚠️ 이 단계를 건너뛰면 "봇으로 구성되어 있지 않습니다" 에러가 발생합니다.

1. 좌측 메뉴 **App Home** 클릭
2. **App Display Name** 섹션에서 **Edit** 클릭
3. Display Name (예: `KnowledgeBot`)과 Default Username (예: `knowledgebot`) 입력 → **Save**

### 3. Socket Mode 활성화

이 프로젝트는 Socket Mode를 사용합니다. Socket Mode는 서버가 Slack에 WebSocket으로 연결하는 방식이라, 공개 URL 없이 로컬에서도 봇을 실행할 수 있습니다.

1. 좌측 메뉴 **Socket Mode** → **Enable Socket Mode** 켜기
2. Token Name 입력 (아무거나, 예: `knowledgebot-local`) → **Generate**
3. 생성된 `xapp-` 토큰 복사 → `.env`의 `SLACK_APP_TOKEN`에 저장

### 4. Bot Token Scopes 설정

1. 좌측 메뉴 **OAuth & Permissions** 이동
2. **Bot Token Scopes** 섹션에서 아래 4개 추가:
   - `chat:write` — 메시지 전송
   - `im:history` — DM 내역 읽기
   - `im:read` — DM 채널 접근
   - `im:write` — DM 채널 열기

### 5. Event Subscriptions 설정

Event Subscriptions는 봇이 어떤 이벤트를 수신할지 구독하는 설정입니다. 구독하지 않으면 DM을 보내도 서버에 이벤트가 전달되지 않습니다.

1. 좌측 메뉴 **Event Subscriptions** → **Enable Events** 켜기
2. **Subscribe to bot events** 섹션에서 `message.im` 추가
3. **Save Changes** 클릭

### 6. 워크스페이스에 설치

1. 좌측 메뉴 **Install App** → **Install to Workspace** 클릭
2. 권한 허용
3. 생성된 `xoxb-` Bot Token 복사 → `.env`의 `SLACK_BOT_TOKEN`에 저장

> **참고**: 회사 워크스페이스에서 관리자 승인이 필요한 경우 "Install to Workspace" 대신 "Request to Workspace Install" 버튼이 표시됩니다. 이 경우 워크스페이스 관리자가 `https://워크스페이스이름.slack.com/admin/apps`에서 승인해야 합니다.

### 토큰 확인 위치

| 토큰 | 위치 |
| --- | --- |
| Bot Token (`xoxb-`) | **OAuth & Permissions** → Bot User OAuth Token |
| App Token (`xapp-`) | **Basic Information** → App-Level Tokens |

---

## 실행 방법

### 1. 사전 준비

아래 계정 및 자격증명이 필요합니다.

- **Slack App**: Socket Mode 활성화, Bot Token(`xoxb-`), App Token(`xapp-`) 발급
- **Google Cloud**: OAuth 2.0 클라이언트 ID/Secret 발급, Gmail API · Drive API 활성화
- **Gemini API Key**: Google AI Studio에서 발급
- **PostgreSQL**: 접속 가능한 DB (Neon, Supabase 등 가능)
- **Fernet Key** 생성:
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

### 2. 설치

```bash
git clone <repo-url>
cd hackethon2

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 3. 환경변수 설정

`.env.example`을 복사해 `.env`를 만들고 값을 채웁니다.

```bash
cp .env.example .env
```

```env
# Slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...

# Google OAuth
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# Gemini
GEMINI_API_KEY=...

# Database (asyncpg 드라이버 필수)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname

# 암호화 키
FERNET_KEY=...

# 앱 주소
APP_BASE_URL=http://localhost:8000
```

> **주의**: `DATABASE_URL`은 반드시 `postgresql+asyncpg://` 형식이어야 합니다.

### 4. DB 마이그레이션

```bash
alembic upgrade head
```

### 5. 서버 실행

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

서버 시작 시 Slack 봇도 함께 백그라운드에서 실행됩니다.

### 6. 동작 확인

```bash
curl http://localhost:8000/health
# {"status": "ok"}
```

---

## 예시 질문

Slack에서 봇에게 DM으로 아래와 같이 질문합니다.

```
건강검진 관련 메일이 있으면 요약해줘
```

```
지난주에 받은 계약서 파일 찾아줘
```

```
김팀장한테 받은 메일 내용 정리해줘
```

---

## 배포 상태

Railway 배포 준비 완료 (`railway.toml` 설정됨).

```toml
startCommand = "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/health"
restartPolicyType = "on_failure"
```

Railway 대시보드에서 위 환경변수를 설정하고 배포하면 됩니다.
`GOOGLE_REDIRECT_URI`와 `APP_BASE_URL`은 Railway 도메인으로 변경해야 합니다.
