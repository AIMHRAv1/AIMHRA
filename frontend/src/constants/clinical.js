// Single source of truth for blood-group input options. Keep in sync with the
// backend validator (patients.serializers.PatientProfileSerializer.validate_blood_group).
export const BLOOD_GROUPS = [
  'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-',
  'A', 'B', 'AB', 'O', 'UNKNOWN',
]

export function bloodGroupOptions(currentValue) {
  const options = [
    { value: '', label: '— not recorded —' },
    ...BLOOD_GROUPS.map((g) => ({ value: g, label: g === 'UNKNOWN' ? 'Unknown' : g })),
  ]
  // Preserve legacy/stored values that are not in the canonical list so an
  // edit never silently overwrites them with blank.
  const cur = (currentValue || '').trim()
  if (cur && !options.some((o) => o.value === cur)) {
    options.splice(1, 0, { value: cur, label: cur })
  }
  return options
}