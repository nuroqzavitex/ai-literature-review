# Run Natively On Ubuntu VPS

Deployment này chạy trực tiếp trên Ubuntu, không dùng Docker:

- Qdrant chạy bằng `qdrant.service` tại `127.0.0.1:6333`.
- Redis chạy trực tiếp bằng `redis-server.service` tại `127.0.0.1:6379`.
- FastAPI chạy bằng `litreview-backend.service` tại `127.0.0.1:8000`.
- Research worker chạy bằng `litreview-worker.service`.
- Next.js chạy bằng `litreview-frontend.service` tại `127.0.0.1:3000`.

Mô hình này phù hợp demo/single VPS. Production authentication dùng Clerk nhưng
backup vẫn phải cấu hình riêng; script setup cài PostgreSQL local, Redis local
cho worker wake-up/status cache, cùng Nginx/TLS/reverse proxy.

## Important Notes

- VPS cần ít nhất 4 GB trống; Python/FastEmbed/Node.js build cần nhiều disk.
- Ubuntu 20.04 đã hết standard support. Script hỗ trợ Focal nhưng không tự nâng
  cấp hệ điều hành; hãy lên kế hoạch chuyển sang Ubuntu LTS còn hỗ trợ.
- Script build Python 3.12.13 từ source trên python.org và cài Node.js 20 qua NodeSource.
- Qdrant dùng binary musl pinned ở version `1.16.2`, tương thích với Ubuntu
  20.04 có glibc cũ. Không dùng `latest`.

## 1. Native Runtime Setup

Đưa source code có script này lên VPS, sau đó chạy bằng `root`:

```bash
cd /path/to/P-178
bash scripts/setup_vps_native_ubuntu_20_04.sh
```

Script cài runtime, PostgreSQL local, dùng `root` cho app services, tạo
systemd unit và chỉ khởi động Qdrant. Nó không cài Docker, không chạy
`apt upgrade`, không thay đổi SSH hay firewall.

Nếu VPS đang chạy stack Docker cũ của project, dừng nó trước để giải phóng port
`3000`, `8000` và `6333`; không thêm `-v` để tránh xóa dữ liệu:

```bash
cd /path/to/P-178
docker compose down
```

## 2. Configure The Application

Khi CD đồng bộ source lần đầu, script dùng `/root/P-178/.env` làm nguồn
cấu hình. Sửa file `.env` trên VPS bằng root:

```bash
nano /root/P-178/.env
```

Thiết lập tối thiểu:

```env
APP_ENV=production
CORS_ORIGINS=https://c3-app-178.io.vn
NEXT_PUBLIC_API_BASE_URL=https://c3-app-178.io.vn/api/v1

# Native PostgreSQL listens on 5432. Both URLs must be explicit because the
# .env.example Docker default uses host port 5433.
DATABASE_URL=postgresql://litreview:REPLACE_PASSWORD@127.0.0.1:5432/litreview
PRODUCT_DATABASE_URL=postgresql://litreview:REPLACE_PASSWORD@127.0.0.1:5432/litreview

LLM_PROVIDER=google
GOOGLE_API_KEY=replace-with-real-secret
GOOGLE_MODEL=gemini-3.1-flash-lite

QDRANT_ENABLED=true
QDRANT_URL=http://127.0.0.1:6333

REDIS_ENABLED=true
REDIS_URL=redis://127.0.0.1:6379/0

CLERK_ISSUER=https://YOUR_INSTANCE.clerk.accounts.dev
CLERK_JWKS_URL=https://YOUR_INSTANCE.clerk.accounts.dev/.well-known/jwks.json
CLERK_AUTHORIZED_PARTIES=https://c3-app-178.io.vn
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_replace
```

Không tự đặt `REPLACE_PASSWORD`: dùng đúng password mà setup script đã ghi vào
block `# BEGIN NATIVE POSTGRES` trong `.env`. Hiện script tạo
`PRODUCT_DATABASE_URL` nhưng chưa ghi đè `DATABASE_URL`; hãy thêm/sửa cả hai URL
trước khi deploy để job store và product store cùng kết nối PostgreSQL native.

Không commit `.env`. Khi CD chạy, script sẽ dùng trực tiếp `.env` để build
backend/frontend, chạy database migration, rồi restart service. Với domain và
reverse proxy, dùng URL HTTPS cho `NEXT_PUBLIC_API_BASE_URL` vì giá trị này
được nhúng vào frontend build.

## 3. Bootstrap And Deploy

Chỉ cần đưa script setup lên VPS lần đầu, không cần clone toàn repository:

```bash
scp scripts/setup_vps_native_ubuntu_20_04.sh root@YOUR_SERVER_IP:/root/
ssh root@YOUR_SERVER_IP 'bash /root/setup_vps_native_ubuntu_20_04.sh'
```

Sau đó cấu hình GitHub CD ở mục bên dưới. GitHub Actions checkout đúng commit
đã pass CI, `rsync` source đến `/root/P-178/`, giữ lại `.env`, `.venv` và
`data/`, rồi chạy native build/restart/health-check. Trước khi build, CD sẽ
tự kiểm tra VPS; nếu thiếu `.env`, systemd unit, Nginx site, hoặc SSL cert,
nó sẽ chạy `scripts/setup_vps_native_ubuntu_20_04.sh` trên VPS để bootstrap
lại.

## CI/CD With GitHub Actions

Workflow `.github/workflows/ci.yml` chạy CI khi có pull request vào `main` và
khi push vào `main` hoặc `develop`: Ruff, pytest với coverage tối thiểu 60%,
TypeScript check và Next.js build. Workflow riêng
`.github/workflows/deploy.yml` chạy sau khi CI trên `main` kết thúc thành công,
SSH vào VPS và đồng bộ source bằng `rsync`, sau đó chạy native deploy script
với đúng commit đã được kiểm tra. Nó cũng có `workflow_dispatch` để deploy thủ
công từ GitHub Actions.

Tạo GitHub Environment tên `production`, rồi khai báo các environment secrets
sau. Đây là SSH key GitHub Actions -> VPS, không phải GitHub deploy key:

| Secret | Giá trị |
|---|---|
| `VPS_HOST` | IP hoặc hostname VPS |
| `VPS_USER` | `root` |
| `VPS_SSH_PRIVATE_KEY` | private key riêng cho GitHub Actions SSH vào VPS |
| `VPS_KNOWN_HOSTS` | public host key đã xác minh của VPS |
| `VPS_SSH_PORT` | port SSH, thường là `22` |

Tùy chọn tạo GitHub Actions variable `VPS_APP_DIR` với giá trị
`/root/P-178`. Nếu không khai báo, workflow dùng đường dẫn này.

Lấy host key từ máy tin cậy, đối chiếu fingerprint với console của nhà cung
cấp VPS, sau đó lưu output vào `VPS_KNOWN_HOSTS`:

```bash
ssh-keyscan -H -p 22 YOUR_SERVER_IP
```

Không dùng `StrictHostKeyChecking=no` hoặc lưu plain private key vào repository.
VPS không cần GitHub deploy key: GitHub Actions lấy source bằng token của
workflow và đẩy source qua SSH. Cách này phù hợp khi bạn không có quyền thêm
deploy key vào repository tổ chức.

## Operations

```bash
sudo systemctl status qdrant.service
sudo systemctl status redis-server.service
sudo systemctl status litreview-backend.service
sudo systemctl status litreview-worker.service
sudo systemctl status litreview-frontend.service

sudo journalctl -u redis-server.service -f
sudo journalctl -u litreview-backend.service -f
sudo journalctl -u litreview-worker.service -f
sudo journalctl -u litreview-frontend.service -f
redis-cli -h 127.0.0.1 ping
curl http://127.0.0.1:8000/health
```

Qdrant data nằm tại `/var/lib/qdrant`; application data và LangGraph checkpoint
nằm trong PostgreSQL do service `postgresql` quản lý. Sao lưu database bằng
`pg_dump`/cơ chế backup PostgreSQL phù hợp, đồng thời lưu cấu hình `.env` an toàn;
không coi `/root/P-178/data` là backup database.

Native VPS runtime trên Ubuntu 20.04 và CI dùng Python 3.12. Lưu ý backend
`Dockerfile` trong repository vẫn dùng Python 3.11 và cần được đồng bộ trước khi
coi container image là tương đương native/CI.

File log của service nằm trong `/root/P-178/logs/`:

- `/root/P-178/logs/qdrant.log`
- `/root/P-178/logs/worker.log`
- `/root/P-178/logs/backend.log`
- `/root/P-178/logs/frontend.log`

Xem nhanh:

```bash
tail -f /root/P-178/logs/backend.log
tail -f /root/P-178/logs/worker.log
tail -f /root/P-178/logs/frontend.log
```

## Network Security

Redis và Qdrant chỉ bind localhost. Frontend/API bind localhost `3000`/`8000`,
còn Nginx public expose `80/443` và reverse proxy từ `c3-app-178.io.vn` vào
FE/BE. CORS và `CLERK_AUTHORIZED_PARTIES` phải dùng domain HTTPS. Clerk xử lý
identity; backend vẫn phải giữ project membership/assignment checks và không
được public internal sandbox endpoints.

SSL được setup tự động bằng Let's Encrypt trong script setup. Nếu DNS chưa trỏ
đúng hoặc port 80 chưa mở, chạy tạm với `ENABLE_SSL=false`; khi mọi thứ ổn thì
rerun setup với:

```bash
CERTBOT_EMAIL=you@example.com ENABLE_SSL=true bash scripts/setup_vps_native_ubuntu_20_04.sh
```
