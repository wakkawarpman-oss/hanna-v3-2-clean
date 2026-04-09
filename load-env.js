'use strict'

const fs = require('node:fs')
const path = require('node:path')

function stripWrappingQuotes (value) {
  if (value.length >= 2) {
    const first = value[0]
    const last = value[value.length - 1]
    if ((first === '"' && last === '"') || (first === "'" && last === "'")) {
      return value.slice(1, -1)
    }
  }
  return value
}

function loadEnv (envPath = path.join(__dirname, '.env')) {
  if (!fs.existsSync(envPath)) {
    return false
  }

  const contents = fs.readFileSync(envPath, 'utf8')
  for (const rawLine of contents.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue

    const separator = line.indexOf('=')
    if (separator <= 0) continue

    const key = line.slice(0, separator).trim()
    if (!key || Object.prototype.hasOwnProperty.call(process.env, key)) continue

    const value = stripWrappingQuotes(line.slice(separator + 1).trim())
    process.env[key] = value
  }

  return true
}

module.exports = { loadEnv }