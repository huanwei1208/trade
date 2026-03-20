type LoadingSkeletonProps = {
  variant?: "hero" | "table" | "panel" | "chart" | "ops";
};

export function LoadingSkeleton({ variant = "panel" }: LoadingSkeletonProps) {
  if (variant === "hero") {
    return (
      <div className="skeleton skeleton--hero">
        <div className="skeleton__line skeleton__line--long" />
        <div className="skeleton__line skeleton__line--short" />
        <div className="skeleton__chips">
          <div className="skeleton__chip" />
          <div className="skeleton__chip" />
          <div className="skeleton__chip" />
        </div>
        <div className="skeleton__cards">
          <div className="skeleton__card" />
          <div className="skeleton__card" />
          <div className="skeleton__card" />
        </div>
      </div>
    );
  }

  if (variant === "table") {
    return (
      <div className="skeleton skeleton--table">
        {Array.from({ length: 6 }).map((_, index) => (
          <div className="skeleton__row" key={index}>
            <div className="skeleton__line skeleton__line--short" />
            <div className="skeleton__line skeleton__line--long" />
            <div className="skeleton__line skeleton__line--short" />
          </div>
        ))}
      </div>
    );
  }

  if (variant === "chart") {
    return (
      <div className="skeleton skeleton--chart">
        <div className="skeleton__toolbar">
          <div className="skeleton__chip" />
          <div className="skeleton__chip" />
          <div className="skeleton__chip" />
        </div>
        <div className="skeleton__chart" />
      </div>
    );
  }

  return (
    <div className={`skeleton skeleton--${variant}`}>
      <div className="skeleton__line skeleton__line--long" />
      <div className="skeleton__line skeleton__line--short" />
      <div className="skeleton__line skeleton__line--long" />
    </div>
  );
}
