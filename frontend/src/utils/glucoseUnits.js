export const hbA1cToMmolMol = (percent) => (Number(percent) - 2.15) * 10.929
export const hbA1cToPercent = (mmolMol) => Number(mmolMol) / 10.929 + 2.15
export const glucoseToMmolL = (mgDl) => Number(mgDl) / 18.0182
export const glucoseToMgDl = (mmolL) => Number(mmolL) * 18.0182

export function toDisplayMeasurement(feature, value) {
  if (value == null) return value
  if (feature === 'hba1c') return Number(hbA1cToPercent(value).toFixed(1))
  if (feature === 'fasting_glucose') return Number(glucoseToMgDl(value).toFixed(1))
  return value
}
