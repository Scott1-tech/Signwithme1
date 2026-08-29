import type { ComparisonResult } from '../types/comparison';

interface Props {
  result: ComparisonResult | null;
  processing?: boolean;
}

export function ComplianceBadge({ result, processing }: Props) {
  if (processing) return <span className="badge badge--neutral">Analysing…</span>;
  if (!result) return <span className="badge badge--neutral">Not analysed</span>;

  const criticalCount =
    result.missing_required.length +
    result.inconsistencies.filter((issue) => issue.severity === 'critical').length +
    result.fmcsa_violations.length;

  if (result.can_sign && result.warnings.length === 0) {
    return <span className="badge badge--good">Ready to sign</span>;
  }
  if (result.can_sign) {
    return (
      <span className="badge badge--warn">
        Ready to sign · {result.warnings.length} warning{result.warnings.length === 1 ? '' : 's'}
      </span>
    );
  }
  return (
    <span className="badge badge--bad">
      Blocked · {criticalCount} critical issue{criticalCount === 1 ? '' : 's'}
    </span>
  );
}
