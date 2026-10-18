import type { ReactNode } from "react";
import { Badge } from "./Badge";
import { classes } from "./classes";

export interface CardProps {
	children: ReactNode;
	radius?: "l" | "xl";
	highlighted?: boolean;
	tag?: string;
	padded?: boolean;
}

export function Card(props: CardProps) {
	const { children, radius = "xl", highlighted, tag, padded = true } = props;

	return (
		<div
			className={classes(
				"card",
				`card--${radius}`,
				highlighted && "card--highlighted",
				padded && "card--padded",
			)}
		>
			{tag && (
				<span className="card__tag">
					<Badge tone="accent">{tag}</Badge>
				</span>
			)}
			{children}
		</div>
	);
}
