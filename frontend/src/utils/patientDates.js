function localDateParts(value) {
  if (!value) return null
  const dateOnly = String(value).match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (dateOnly) return dateOnly.slice(1).map(Number)
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return [date.getFullYear(), date.getMonth() + 1, date.getDate()]
}

function dayNumber([year, month, day]) {
  return Date.UTC(year, month - 1, day) / 86400000
}

export function ageFromDateOfBirth(dateOfBirth, today = new Date()) {
  const birth = localDateParts(dateOfBirth)
  if (!birth) return null
  let age = today.getFullYear() - birth[0]
  if (
    today.getMonth() + 1 < birth[1]
    || (today.getMonth() + 1 === birth[1] && today.getDate() < birth[2])
  ) age -= 1
  return age >= 0 ? age : null
}

export function ageAtDateOfBirth(dateOfBirth, date) {
  const [year, month, day] = localDateParts(date) || []
  if (!year || !month || !day) return null
  return ageFromDateOfBirth(dateOfBirth, new Date(year, month - 1, day))
}

export function currentGestationalWeek(weekAtRegistration, registeredAt, today = new Date()) {
  const start = localDateParts(registeredAt)
  if (weekAtRegistration == null || !start) return null
  const elapsedDays = Math.max(0, dayNumber(localDateParts(today)) - dayNumber(start))
  return Math.min(45, Number(weekAtRegistration) + Math.floor(elapsedDays / 7))
}
