import { useMemo } from 'react';

interface Props {
  value: string; // ISO yyyy-mm-dd, as the native input produces
  onChange: (value: string) => void;
  label?: string;
}

/** Renders the ISO value the way the contract will actually print it. */
export function formatForContract(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const [, year, month, day] = match;
  return `${month}/${day}/${year}`;
}

export function DatePicker({ value, onChange, label = 'Contract date' }: Props) {
  const preview = useMemo(() => formatForContract(value), [value]);

  return (
    <label className="date-picker">
      <span className="date-picker__label">{label}</span>
      <input
        type="date"
        className="date-picker__input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      {/* The input speaks ISO; the PDF prints MM/DD/YYYY. Showing both stops
          the reviewer being surprised by the finished document. */}
      <span className="date-picker__preview">prints as {preview}</span>
    </label>
  );
}
