import type { ReactNode } from "react";
import { Avatar, Indicator } from "../../components";

export interface StageProps {
	name: string;
	role: string;
	speaking: boolean;
	children?: ReactNode;
}

export function Stage(props: StageProps) {
	const { name, role, speaking, children } = props;

	return (
		<section className="stage" aria-label={`Говорит: ${name}`}>
			<div className="stage__content">
				{children ?? <Avatar name={name} size="xl" />}
			</div>
			<div className="stage__caption">
				{speaking && <Indicator kind="speaking" />}
				<strong>{name}</strong>
				<span>{role}</span>
			</div>
		</section>
	);
}
