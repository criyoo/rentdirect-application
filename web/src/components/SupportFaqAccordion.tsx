import { useState } from 'react'
import { HiChevronDown } from 'react-icons/hi'

export type SupportFaqItem = {
    question: string
    answer: string
}

type SupportFaqAccordionProps = {
    items: readonly SupportFaqItem[]
    idPrefix: string
}

export default function SupportFaqAccordion({ items, idPrefix }: SupportFaqAccordionProps) {
    const [openIndex, setOpenIndex] = useState<number | null>(null)

    return (
        <div className="space-y-3">
            {items.map((item, index) => {
                const isOpen = openIndex === index
                const answerId = `${idPrefix}-answer-${index}`

                return (
                    <div key={item.question} className="overflow-hidden rounded-xl border border-gray-200 bg-white">
                        <button
                            type="button"
                            onClick={() => setOpenIndex(isOpen ? null : index)}
                            aria-expanded={isOpen}
                            aria-controls={answerId}
                            className="flex w-full items-center justify-between gap-4 px-4 py-4 text-left transition hover:bg-blue-50/60"
                        >
                            <span className="text-sm font-semibold text-gray-900">{item.question}</span>
                            <HiChevronDown className={`h-5 w-5 shrink-0 text-blue-600 transition-transform ${isOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
                        </button>
                        {isOpen && (
                            <div id={answerId} className="border-t border-gray-100 bg-gray-50 px-4 py-4 text-sm leading-6 text-gray-600">
                                {item.answer}
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}
