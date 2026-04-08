#!/usr/bin/env node
'use strict'

const fs = require('node:fs')

const file = 'config.calibrated.json'
if (fs.existsSync(file)) {
  fs.unlinkSync(file)
  console.log(`Removed ${file}`)
} else {
  console.log(`${file} not found`)
}
