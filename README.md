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
사용자 → Slack DM
           │
           ▼
     Google 연동 여부 확인
           │
    미연동 ─┤─ 연동됨
           │           │
    OAuth 버튼 발송     ▼
                 Gemini로 검색 키워드 추출
                       │
                       ▼
              Gmail + Drive 병렬 검색
                       │
                       ▼
              Gemini 2.5 Flash로 요약
                       │
                       ▼
                Slack DM으로 답변 전송
```

1. 봇이 DM을 수신하면 DB에서 해당 Slack 유저를 조회합니다.
2. 미연동 유저에게는 Google OAuth 버튼을 보냅니다. 버튼 클릭 시 `/auth/google/callback`으로 리다이렉트돼 토큰을 DB에 저장합니다.
3. 연동된 유저의 질문은 Gemini가 핵심 키워드로 변환한 뒤 Gmail API와 Drive API로 검색합니다.
4. 검색 결과를 Gemini에 전달해 한국어 요약을 생성하고 DM으로 응답합니다.

---

## 기술 스택

| 분류 | 라이브러리 / 서비스 |
|------|---------------------|
| 웹 프레임워크 | FastAPI 0.115, Uvicorn 0.30 |
| Slack | slack-bolt 1.21 (Socket Mode) |
| Google API | google-api-python-client, google-auth-oauthlib |
| AI | google-genai (Gemini 2.5 Flash) |
| DB | PostgreSQL + SQLAlchemy 2.0 (asyncpg) |
| 마이그레이션 | Alembic 1.14 |
| 암호화 | cryptography (Fernet) |
| 설정 | pydantic-settings |
| 배포 | Railway |

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

---

## 향후 계획

- [ ] Gmail 검색 범위 확장 (현재 최대 10건)
- [ ] Drive 파일 내용 본문 읽기 (현재 파일명/링크만 반환)
- [ ] 멀티턴 대화 지원 (현재 단일 질문-응답)
- [ ] 슬래시 커맨드(`/search`) 지원
