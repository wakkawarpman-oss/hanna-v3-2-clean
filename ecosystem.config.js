module.exports = {
  apps: [
    {
      name: 'hanna-parser',
      script: './app-opt.js',
      instances: 'max',
      exec_mode: 'cluster',
      env_production: {
        NODE_ENV: 'production',
        NODE_OPTIONS: '--max-old-space-size=512 --optimize-for-size',
        PARSER_CACHE_SIZE: '10000'
      },
      max_memory_restart: '400M',
      kill_timeout: 5000,
      listen_timeout: 3000,
      error_file: './logs/err.log',
      out_file: './logs/out.log',
      log_file: './logs/combined.log',
      time: true
    }
  ]
}
