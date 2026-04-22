## Flow Tracking (MT5 + React + Overlay)

Local app to track per-session flow notes and render them as overlays on top of an `lightweight-charts` candlestick chart.

### Symbols (BlackBull MT5)
- `DJ30.f`
- `USTEC.f`
- `US500.f`

### Run (Windows)
1. Ensure BlackBull MT5 is installed and logged in:
   - `C:\Program Files\BlackBull Markets MT5\terminal64.exe`
2. Ensure repo venv exists (recommended): `e:\Trade folder\Trading_analyze\.venv\Scripts\python.exe`
3. Install backend deps:

```bash
e:\Trade folder\Trading_analyze\.venv\Scripts\python.exe -m pip install -r flow_tracking\backend\requirements.txt
```

4. Install frontend deps (one time):

```bash
cd flow_tracking\frontend
npm install
```

5. Dev mode (2 terminals):

```bash
# terminal 1
e:\Trade folder\Trading_analyze\.venv\Scripts\python.exe flow_tracking\backend\app.py

# terminal 2
cd flow_tracking\frontend
npm run dev
```

Then open:
- Backend health: `http://127.0.0.1:5057/api/health`
- Frontend dev: `http://127.0.0.1:5173`

### Production-ish (single server)
Build frontend and serve `frontend/dist` from Flask:

```bash
cd flow_tracking\frontend
npm run build
e:\Trade folder\Trading_analyze\.venv\Scripts\python.exe ..\backend\app.py
```

### Start script
- `flow_tracking\START.bat` launches MT5, fetches data via API calls on demand, then starts the backend and opens the app.

