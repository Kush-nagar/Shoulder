export default function PracticeLoading() {
  return (
    <div role="status" aria-label="Loading practice" aria-busy="true">
      <div className="h-9 w-36 rounded-lg bg-surface-subtle md:h-11" />
      <div className="mt-4 h-6 max-w-[48ch] rounded-lg bg-surface-subtle" />
      <div className="mt-8 grid gap-3 md:grid-cols-2 lg:grid-cols-3 lg:gap-4">
        {[0, 1, 2, 3, 4, 5].map((key) => (
          <div key={key} className="flex gap-3 md:block">
            <div className="aspect-video w-24 shrink-0 rounded-lg bg-surface-subtle md:w-full" />
            <div className="flex-1 md:mt-2">
              <div className="h-5 w-3/4 rounded bg-surface-subtle" />
              <div className="mt-1 h-4 w-1/2 rounded bg-surface-subtle" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
