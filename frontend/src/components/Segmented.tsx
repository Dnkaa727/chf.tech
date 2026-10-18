import { classes } from "./classes";

export interface SegmentedProps<V extends string> {
	options: { value: V; label: string }[];
	value: V;
	onChange: (value: V) => void;
}

export function Segmented<V extends string>(props: SegmentedProps<V>) {
	const { options, value, onChange } = props;

	return (
		<div className="segmented" role="tablist">
			{options.map((o) => (
				<button
					key={o.value}
					type="button"
					role="tab"
					aria-selected={o.value === value}
					className={classes(
						"segmented__item",
						o.value === value && "segmented__item--selected",
					)}
					onClick={() => onChange(o.value)}
				>
					{o.label}
				</button>
			))}
		</div>
	);
}
