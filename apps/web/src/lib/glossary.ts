/** Plain-words explanations for data quality vocabulary, shown as inline hints. */
export const GLOSSARY = {
  score:
    "The share of records that pass their checks, averaged per quality dimension and then across dimensions. 100% means every checked record passes.",
  completeness: "Are values present? Missing (NULL) and blank values count against it.",
  validity: "Do present values have the right type, format, range and allowed values?",
  consistency: "Do values agree with each other: schema, formats, references between tables, column comparisons?",
  uniqueness: "Are keys and rows unique, with no duplicates?",
  freshness: "Is the newest data recent enough?",
  volume: "Is the number of rows within the expected range?",
  profile:
    "A summary of each column computed inside the source: types, missing values, distinct values, ranges, common values and value shapes.",
  tolerance:
    "How many failing rows still count as a pass, as a count or a percent. Zero by default: any failing row fails the check.",
  severity: "Error checks fail the scan's gate and alert by default; warnings are reported but softer.",
  anomaly:
    "A metric that moved far from its own history (more than 3.5 robust deviations from the median of recent scans), like a row count that suddenly drops.",
  incident:
    "One open problem found by an alert rule. It stays open while later scans still show it, notifies once, and resolves itself when a scan shows it gone.",
  readOnly:
    "DataQuality only ever runs SELECT statements, in a read-only session where the database supports one. Use a login that can only read.",
  shape: "A value's pattern: letters become A or a and digits 9, so 'KA-01' has the shape 'AA-99'.",
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
