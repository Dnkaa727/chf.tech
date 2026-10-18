export interface IndicatorProps {
	kind: "speaking" | "count";
	count?: number;
}

export function Indicator(props: IndicatorProps) {
	const { kind, count } = props;

	if (kind === "count")
		return (
			<span className="indicator indicator--count">
				{count && count > 99 ? "99+" : count}
			</span>
		);

	return (
		<span className="indicator indicator--speaking" aria-label="Говорит">
			<i />
			<i />
			<i />
		</span>
	);
}
