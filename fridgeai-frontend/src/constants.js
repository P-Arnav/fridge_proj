export const C = {
  bg:       'transparent', // Let gradient handle this
  surface:  'rgba(20, 30, 48, 0.4)', // Glass surface
  surface2: 'rgba(255, 255, 255, 0.03)',
  border:   'rgba(255, 255, 255, 0.08)',
  border2:  'rgba(255, 255, 255, 0.12)',
  teal:     '#00d4aa',
  blue:     '#3b9eff',
  accent:   '#8854d0',
  text:     '#f0f4f8',
  muted:    '#829ab1',
  critical: '#ff4d6d',
  warn:     '#fbbf24',
  safe:     '#34d399',
}

export const riskColor = (p) =>
  p == null ? C.muted : p > 0.80 ? C.critical : p > 0.50 ? C.warn : C.safe

export const riskLabel = (p) =>
  p == null ? 'PENDING' : p > 0.80 ? 'CRITICAL' : p > 0.50 ? 'USE SOON' : 'SAFE'

export const CATEGORIES = [
  'dairy', 'protein', 'meat', 'vegetable', 'fruit', 'fish', 'cooked', 'beverage',
]

export const ALERT_COLOR = {
  CRITICAL_ALERT:  C.critical,
  WARNING_ALERT:   C.warn,
  USE_TODAY_ALERT: C.teal,
}

export const ALERT_LABEL = {
  CRITICAL_ALERT:  'CRITICAL',
  WARNING_ALERT:   'WARNING',
  USE_TODAY_ALERT: 'USE TODAY',
}
