"use client";
import { GROUPS, meta, format } from "../lib/metrics";

/* Three states kept visually distinct: a value; a metric that does not exist
   for this sector; and one the filer never tagged. The middle case is not a
   weakness and must not read like one. */
export default function MetricTable({ metrics, gaps, notApplicable }) {
  const gapSet = new Set(gaps || []);
  const naSet = new Set(notApplicable || []);
  const byGroup = {};

  for (const [key, v] of Object.entries(metrics)) {
    (byGroup[meta(key).group] = byGroup[meta(key).group] || []).push([key, v]);
  }
  for (const key of gapSet) {
    (byGroup[meta(key).group] = byGroup[meta(key).group] || []).push([key, null]);
  }

  return (
    <div>
      {GROUPS.filter((g) => byGroup[g]?.length).map((g) => (
        <div key={g} style={{ marginBottom: 34 }}>
          <div className="label" style={{ marginBottom: 10 }}>{g}</div>
          <table>
            <tbody>
              {byGroup[g]
                .sort((a, b) => meta(a[0]).label.localeCompare(meta(b[0]).label, "tr"))
                .map(([key, v]) => (
                  <tr key={key}>
                    <td>
                      <div style={{ fontSize: 14 }}>{meta(key).label}</div>
                      {meta(key).note && <div className="micro">{meta(key).note}</div>}
                    </td>
                    <td className="r">
                      {v === null
                        ? <span className="dim" style={{ fontSize: 13 }}
                                title="Şirket bu kalemi XBRL'de raporlamamış">veri yok</span>
                        : format(key, v)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ))}
      {naSet.size > 0 && (
        <div>
          <div className="label" style={{ marginBottom: 8 }}>Bu sektörde geçerli değil</div>
          <div className="small">Aşağıdakiler kavram olarak bu sektörde bulunmaz — eksik veri değildir.</div>
          <div className="micro" style={{ marginTop: 8, lineHeight: 1.9 }}>
            {[...naSet].map((k) => meta(k).label).join(" · ")}
          </div>
        </div>
      )}
    </div>
  );
}
