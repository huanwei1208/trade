import type { Locale } from "../lib/api";
import { useI18n } from "../lib/i18n";

type TopNavProps = {
  title: string;
  subtitle: string;
  asOf: string;
  locale: Locale;
  onLocaleChange: (locale: Locale) => void;
  onRefresh: () => void;
};

export function TopNav({ title, subtitle, asOf, locale, onLocaleChange, onRefresh }: TopNavProps) {
  const { t } = useI18n();
  return (
    <div className="top-nav">
      <div>
        <div className="top-nav__eyebrow">{t("app.workspaceEyebrow")}</div>
        <h1 className="top-nav__title">{title}</h1>
        <p className="top-nav__subtitle">{subtitle}</p>
      </div>
      <div className="top-nav__tools">
        <div className="top-nav__asof">
          <span className="dot dot--live" />
          <span>{t("common.timeAsOf", { date: asOf })}</span>
        </div>
        <label className="top-nav__select">
          <span>{t("topNav.lang")}</span>
          <select value={locale} onChange={(event) => onLocaleChange(event.target.value as Locale)}>
            <option value="zh-CN">中文</option>
            <option value="en-US">English</option>
          </select>
        </label>
        <button type="button" className="button button--primary" onClick={onRefresh}>
          {t("topNav.refresh")}
        </button>
      </div>
    </div>
  );
}
