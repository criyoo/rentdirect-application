import { Fragment, ReactNode, useMemo } from 'react'
import { Link } from 'react-router-dom'
import howItWorksContent from './how-it-works.md?raw'

type MarkdownBlock =
    | { type: 'h1' | 'h2' | 'h3' | 'h4'; text: string }
    | { type: 'paragraph'; text: string }
    | { type: 'list'; items: string[] }

function renderInlineMarkdown(text: string): ReactNode[] {
    return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, index) => {
        if (part.startsWith('**') && part.endsWith('**')) {
            return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>
        }
        return <Fragment key={`${part}-${index}`}>{part}</Fragment>
    })
}

function parseMarkdown(markdown: string): MarkdownBlock[] {
    const blocks: MarkdownBlock[] = []
    const lines = markdown.split('\n')
    let paragraphLines: string[] = []
    let listItems: string[] = []

    const flushParagraph = () => {
        const text = paragraphLines.join(' ').trim()
        if (text) {
            blocks.push({ type: 'paragraph', text })
        }
        paragraphLines = []
    }

    const flushList = () => {
        if (listItems.length > 0) {
            blocks.push({ type: 'list', items: [...listItems] })
        }
        listItems = []
    }

    for (const rawLine of lines) {
        const line = rawLine.trim()
        if (!line) {
            flushParagraph()
            flushList()
            continue
        }

        const headingMatch = line.match(/^(#{1,4})\s+(.*)$/)
        if (headingMatch) {
            flushParagraph()
            flushList()
            const level = headingMatch[1].length
            const text = headingMatch[2].trim()
            const type = level === 1 ? 'h1' : level === 2 ? 'h2' : level === 3 ? 'h3' : 'h4'
            blocks.push({ type, text })
            continue
        }

        const listMatch = line.match(/^\*\s+(.*)$/)
        if (listMatch) {
            flushParagraph()
            listItems.push(listMatch[1].trim())
            continue
        }

        flushList()
        paragraphLines.push(line)
    }

    flushParagraph()
    flushList()

    return blocks
}

export default function HowItWorksPage() {
    const blocks = useMemo(() => parseMarkdown(howItWorksContent), [])

    return (
        <div className="min-h-screen bg-[linear-gradient(180deg,#f8fbff_0%,#eef5ff_45%,#ffffff_100%)]">
            <section className="border-b border-blue-100 bg-[radial-gradient(circle_at_top_left,_rgba(37,99,235,0.14),_transparent_40%),linear-gradient(135deg,#f9fbff_0%,#eef4ff_45%,#ffffff_100%)]">
                <div className="container-modern py-14 md:py-20">
                    <div className="max-w-4xl">
                        <div className="inline-flex items-center rounded-full border border-blue-200 bg-white/80 px-4 py-2 text-xs font-semibold uppercase tracking-[0.24em] text-blue-700">
                            How RentDirect Works
                        </div>
                        <h1 className="mt-6 text-4xl font-bold tracking-tight text-slate-950 md:text-5xl">
                            Your Complete Rental Guide
                        </h1>
                        <p className="mt-5 max-w-3xl text-lg leading-8 text-slate-600">
                            Learn how to find your perfect home or list your property in five simple steps.
                        </p>
                        <div className="mt-8 flex flex-wrap gap-3">
                            <Link to="/search" className="btn btn-primary">
                                Search Properties
                            </Link>
                            <Link to="/register" className="btn btn-outline">
                                Create Account
                            </Link>
                        </div>
                    </div>
                </div>
            </section>

            <section className="py-12 md:py-16">
                <div className="container-modern">
                    <div className="mx-auto w-full max-w-4xl rounded-[2rem] border border-slate-200 bg-white p-6 shadow-sm md:p-10">
                        <div className="space-y-8">
                            {blocks.map((block, index) => {
                                if (block.type === 'h1') {
                                    return (
                                        <div key={index} className="border-b border-slate-200 pb-6">
                                            <h2 className="text-3xl font-bold tracking-tight text-slate-950 md:text-4xl">
                                                {renderInlineMarkdown(block.text)}
                                            </h2>
                                        </div>
                                    )
                                }

                                if (block.type === 'h2') {
                                    return (
                                        <div key={index} className="pt-2">
                                            <h3 className="text-2xl font-bold tracking-tight text-slate-950 md:text-3xl">
                                                {renderInlineMarkdown(block.text)}
                                            </h3>
                                        </div>
                                    )
                                }

                                if (block.type === 'h3') {
                                    return (
                                        <div key={index}>
                                            <h4 className="text-xl font-semibold text-blue-700">
                                                {renderInlineMarkdown(block.text)}
                                            </h4>
                                        </div>
                                    )
                                }

                                if (block.type === 'h4') {
                                    return (
                                        <div key={index} className="mt-0 mb-0">
                                            <h5 className="text-lg font-semibold text-slate-800">
                                                {renderInlineMarkdown(block.text)}
                                            </h5>
                                        </div>
                                    )
                                }

                                if (block.type === 'list') {
                                    return (
                                        <ul key={index} className="space-y-3 rounded-2xl bg-slate-50 p-5 text-base leading-7 text-slate-700">
                                            {block.items.map((item, itemIndex) => (
                                                <li key={`${index}-${itemIndex}`} className="flex gap-3">
                                                    <span className="mt-2 h-2.5 w-2.5 rounded-full bg-blue-600" />
                                                    <span>{renderInlineMarkdown(item)}</span>
                                                </li>
                                            ))}
                                        </ul>
                                    )
                                }

                                return (
                                    <p key={index} className="text-base leading-8 text-slate-700 md:text-lg mb-2">
                                        {renderInlineMarkdown(block.text)}
                                    </p>
                                )
                            })}
                        </div>
                    </div>
                </div>
            </section>
        </div>
    )
}