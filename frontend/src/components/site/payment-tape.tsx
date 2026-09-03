/*
  A slow departures-board of route state. Decorative, so it is hidden from
  assistive technology and pauses on hover and under reduced motion.
*/
const ENTRIES: Array<[string, string, "ok" | "fail" | "held"]> = [
  ["HDFC_BANK", "upi_collect", "ok"],
  ["ICICI_BANK", "issuer_declined", "fail"],
  ["SBIN", "netbanking", "ok"],
  ["AXIS_BANK", "card_3ds", "ok"],
  ["ICICI_BANK", "do_not_honour", "fail"],
  ["KOTAK", "upi_intent", "ok"],
  ["ICICI_BANK", "reroute · r14", "held"],
  ["YESBANK", "card_debit", "ok"],
  ["ICICI_BANK", "gateway_timeout", "fail"],
  ["INDUSIND", "upi_collect", "ok"],
  ["HDFC_BANK", "holdout · control", "held"],
  ["FEDERAL", "netbanking", "ok"],
];

function Row({ index }: { index: number }) {
  return (
    <div className="tape-run" aria-hidden={index > 0 ? "true" : undefined}>
      {ENTRIES.map((entry, position) => (
        <span className="tape-entry" data-state={entry[2]} key={`${entry[0]}-${position}`}>
          <i className="tape-dot" />
          <b className="mono">{entry[0]}</b>
          <span className="mono">{entry[1]}</span>
        </span>
      ))}
    </div>
  );
}

export function PaymentTape() {
  return (
    <div className="tape" aria-hidden="true">
      <div className="tape-track">
        <Row index={0} />
        <Row index={1} />
      </div>
    </div>
  );
}
