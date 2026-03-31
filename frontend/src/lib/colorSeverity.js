export function colorSeverity(score) {
  if (score >= 0.8) return '#ff4d5d'
  if (score >= 0.55) return '#ffa540'
  if (score >= 0.3) return '#f8df72'
  return '#56d58f'
}
