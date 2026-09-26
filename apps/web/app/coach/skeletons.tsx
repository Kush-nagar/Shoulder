import { Bone, keys, Loading } from "../../components/skeleton";

/** The coach page header bar: title left, "Upload match" right. */
export function CoachHead({ title = "w-40" }: { title?: string }) {
  return (
    <div className="flex items-end justify-between gap-6 px-5 pt-6 pb-5 md:px-6 lg:px-8 lg:pt-8">
      <div>
        <Bone className={`h-8 ${title}`} />
        <Bone className="mt-2 h-4 w-28" />
      </div>
      <Bone className="h-9 w-36" />
    </div>
  );
}

export function CoachRows({ count = 5 }: { count?: number }) {
  return (
    <ul className="divide-y divide-line rounded-xl border border-line">
      {keys(count).map((key) => (
        <li key={key} className="flex items-center gap-4 px-4 py-3">
          <Bone className="h-4 w-16 rounded-sm" />
          <div className="flex-1">
            <Bone className="h-4 w-2/5 max-w-60 rounded-sm" />
            <Bone className="mt-1.5 h-3 w-1/4 max-w-40 rounded-sm" />
          </div>
        </li>
      ))}
    </ul>
  );
}

export { Bone, Loading };
