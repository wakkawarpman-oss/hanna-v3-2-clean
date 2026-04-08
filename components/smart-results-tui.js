'use strict'

class SmartResultsTui {
  constructor (resultsTable) {
    this.resultsTable = resultsTable
  }

  displayClusters (clusters) {
    const headers = ['RANK', 'SCORE', 'ФІО', 'РОК', 'МІСТО', 'MATCHES']
    const data = (clusters || []).slice(0, 15).map((cluster, index) => {
      const best = cluster.bestMatch || { parsed: {} }
      return [
        String(index + 1),
        Number(cluster.score || 0).toFixed(1),
        (cluster.fio || '—').slice(0, 20),
        best.parsed.birthYear || '—',
        best.parsed.city || '—',
        String(cluster.count || 0)
      ]
    })

    this.resultsTable.setData({
      headers,
      data: data.length ? data : [['-', '0.0', '—', '—', '—', '0']]
    })
  }
}

module.exports = {
  SmartResultsTui
}
