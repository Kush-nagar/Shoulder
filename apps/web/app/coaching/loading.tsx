/** Same geometry as the coach list: title, lead, then result rows. */
export default function CoachingLoading() {
  return (
    <div role="status" aria-busy="true" aria-label="Loading">
      <div className="h-9 w-56 rounded-lg bg-surface-subtle" />
      <div className="mt-4 h-5 w-full max-w-[520px] rounded bg-surface-subtle" />
      <ul className="mt-10 divide-y divide-line border-y border-line lg:max-w-[calc(100%-368px)]">
        {[0, 1, 2].map((row) => (
          <li key={row} className="py-5">
            <div className="h-7 w-48 rounded bg-surface-subtle" />
            <div className="mt-3 h-4 w-72 max-w-full rounded bg-surface-subtle" />
          </li>
        ))}
      </ul>
    </div>
  );
}
