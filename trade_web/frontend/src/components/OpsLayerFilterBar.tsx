import type { ReactNode } from "react";

type FilterOption = {
  value: string;
  label: string;
};

type OpsLayerFilterBarProps = {
  typeFilter: string;
  statusFilter: string;
  onTypeFilter: (value: string) => void;
  onStatusFilter: (value: string) => void;
  typeOptions: FilterOption[];
  statusOptions: FilterOption[];
  extra?: ReactNode;
};

export function OpsLayerFilterBar({
  typeFilter,
  statusFilter,
  onTypeFilter,
  onStatusFilter,
  typeOptions,
  statusOptions,
  extra,
}: OpsLayerFilterBarProps) {
  return (
    <div className="ops-layer-filterbar">
      <div className="ops-layer-filterbar__group">
        {typeOptions.map((option) => (
          <button
            key={option.value}
            type="button"
            className={typeFilter === option.value ? "is-active" : ""}
            onClick={() => onTypeFilter(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <div className="ops-layer-filterbar__group">
        {statusOptions.map((option) => (
          <button
            key={option.value}
            type="button"
            className={statusFilter === option.value ? "is-active" : ""}
            onClick={() => onStatusFilter(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      {extra && <div className="ops-layer-filterbar__extra">{extra}</div>}
    </div>
  );
}
