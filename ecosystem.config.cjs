module.exports = {
  apps: [{
    name: "kareem-market",
    cwd: "/home/root/projects/kareem",
    script: "/home/root/projects/kareem/venv/bin/gunicorn",
    args: "--workers 3 --bind 127.0.0.1:4040 wsgi:app",
    interpreter: "none",
    autorestart: true,
    watch: false,
    max_memory_restart: "400M",
    env: {
      PYTHONUNBUFFERED: "1",
      TZ: "Asia/Aden"
    },
    time: true,
    merge_logs: true,
    error_file: "/home/root/projects/kareem/logs/error.log",
    out_file: "/home/root/projects/kareem/logs/out.log"
  }]
};
