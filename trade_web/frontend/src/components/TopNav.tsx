import type { Locale } from "../lib/api";

type TopNavProps = {
  title: string;
  subtitle: string;
  asOf: string;
  locale: Locale;
  onLocaleChange: (locale: Locale) => void;
  onRefresh: () => void;
};

export function TopNav({ title, subtitle, asOf, locale, onLocaleChange, onRefresh }: TopNavProps) {
  return (
    <div className="top-nav">
      <div>
        <div className="top-nav__eyebrow">Trade Decision Workspace</div>
        <h1 className="top-nav__title">{title}</h1>
        <p className="top-nav__subtitle">{subtitle}</p>
      </div>
      <div className="top-nav__tools">
        <div className="top-nav__asof">
          <span className="dot dot--live" />
          <span>{asOf}</span>
        </div>
        <label className="top-nav__select">
          <span>Lang</span>
          <select value={locale} onChange={(event) => onLocaleChange(event.target.value as Locale)}>
            <option value="zh-CN">中文</option>
            <option value="en-US">English</option>
          </select>
        </label>
        <button type="button" className="button button--primary" onClick={onRefresh}>
          Refresh
        </button>
      </div>
    </div>
  );
}
