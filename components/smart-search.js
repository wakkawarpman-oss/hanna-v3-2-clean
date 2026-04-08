'use strict'

class SmartSearch {
  constructor () {
    this.fuzzyThreshold = 0.75
    this.boostFactors = {
      fio: 3.0,
      birthYear: 2.5,
      phone: 2.0,
      address: 1.8,
      city: 1.5,
      fop: 1.2
    }
  }

  normalize (text) {
    return String(text || '')
      .normalize('NFC')
      .toLowerCase()
      .replace(/[^\p{L}\p{N}\s+]/gu, ' ')
      .replace(/\s+/g, ' ')
      .trim()
  }

  scoreResult (parsed, query) {
    let score = 0
    const details = {}
    const safeParsed = parsed || {}
    const queryText = this.normalize(query)

    if (!queryText) {
      return { score: 0, details: {}, rank: 'D' }
    }

    const queryTokens = queryText.split(' ').filter(Boolean)

    if (safeParsed.fio && this.fuzzyMatch(safeParsed.fio, queryText, 0.9)) {
      score += this.boostFactors.fio * 0.95
      details.fioMatch = 0.95
    }

    for (const [field, value] of Object.entries(safeParsed)) {
      if (!value) continue
      const boost = this.boostFactors[field] || 1
      const valueText = this.normalize(value)
      const hasTokenMatch = queryTokens.some((token) => token.length >= 3 && this.fuzzyMatch(valueText, token, 0.75))
      const contains = queryTokens.some((token) => token.length >= 3 && valueText.includes(token))

      if (contains || hasTokenMatch) {
        score += boost * 0.7
        details[field] = 0.7
      }
    }

    const queryPenalty = Math.max(0, 1 - queryText.length / 150)
    score *= queryPenalty

    return {
      score: Math.round(score * 100) / 100,
      details,
      rank: score > 4.0 ? 'A' : score > 2.5 ? 'B' : score > 1.0 ? 'C' : 'D'
    }
  }

  fuzzyMatch (left, right, threshold = this.fuzzyThreshold) {
    const a = this.normalize(left)
    const b = this.normalize(right)
    if (!a || !b) return false

    if (a.includes(b) || b.includes(a)) {
      return true
    }

    const distance = this.levenshtein(a, b)
    const maxLength = Math.max(a.length, b.length)
    if (maxLength === 0) return false

    return (distance / maxLength) <= (1 - threshold)
  }

  levenshtein (a, b) {
    const cols = a.length + 1
    const rows = b.length + 1
    const matrix = Array.from({ length: rows }, () => Array(cols).fill(0))

    for (let i = 0; i < cols; i++) matrix[0][i] = i
    for (let j = 0; j < rows; j++) matrix[j][0] = j

    for (let j = 1; j < rows; j++) {
      for (let i = 1; i < cols; i++) {
        const indicator = a[i - 1] === b[j - 1] ? 0 : 1
        matrix[j][i] = Math.min(
          matrix[j][i - 1] + 1,
          matrix[j - 1][i] + 1,
          matrix[j - 1][i - 1] + indicator
        )
      }
    }

    return matrix[rows - 1][cols - 1]
  }
}

class SearchResults {
  groupResults (results) {
    const clusters = {}

    for (const result of results || []) {
      const parsed = result.parsed || {}
      const key = this.getClusterKey(parsed)
      if (!key) continue

      if (!clusters[key]) {
        clusters[key] = {
          fio: parsed.fio || '',
          count: 0,
          score: 0,
          items: [],
          bestMatch: result
        }
      }

      clusters[key].count += 1
      clusters[key].items.push(result)
      if ((result.score || 0) > clusters[key].score) {
        clusters[key].score = result.score
        clusters[key].bestMatch = result
      }
    }

    return Object.values(clusters)
      .sort((a, b) => b.score - a.score)
      .slice(0, 10)
  }

  getClusterKey (parsed) {
    return [
      (parsed.fio || '').slice(0, 20),
      parsed.birthYear || '',
      parsed.city || ''
    ].filter(Boolean).join('|')
  }
}

module.exports = {
  SmartSearch,
  SearchResults
}
