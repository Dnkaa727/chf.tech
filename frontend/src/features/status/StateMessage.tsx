import type { ReactNode } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { IconProp } from "@fortawesome/fontawesome-svg-core";

export interface StateMessageProps {
	icon: IconProp;
	title: string;
	text: string;
	action?: ReactNode;
}

export function StateMessage(props: StateMessageProps) {
	const { icon, title, text, action } = props;

	return (
		<section className="state-message">
			<span className="state-message__icon">
				<FontAwesomeIcon icon={icon} />
			</span>
			<h2>{title}</h2>
			<p>{text}</p>
			{action}
		</section>
	);
}
