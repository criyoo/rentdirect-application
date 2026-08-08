import { Fragment, ReactNode, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import BrandLogo from '@/components/BrandLogo'
import howItWorksContent from './how-it-works.md?raw'
import landlordContent from './landlords.md?raw'
import tenantContent from './tenants.md?raw'

type MarkdownBlock =
    | { type: 'h1' | 'h2' | 'h3' | 'h4'; text: string }
    | { type: 'paragraph'; text: string }
    | { type: 'list'; items: string[] }
    | { type: 'step'; title: string; items: string[] }
    | { type: 'faq'; question: string; answer: string }

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

function groupStepBlocks(blocks: MarkdownBlock[]): MarkdownBlock[] {
    const grouped: MarkdownBlock[] = []

    for (let index = 0; index < blocks.length; index += 1) {
        const block = blocks[index]
        const nextBlock = blocks[index + 1]
        if (block.type === 'h3' && nextBlock?.type === 'list') {
            grouped.push({ type: 'step', title: block.text, items: nextBlock.items })
            index += 1
            continue
        }
        grouped.push(block)
    }

    return grouped
}

function groupFaqBlocks(blocks: MarkdownBlock[]): MarkdownBlock[] {
    const grouped: MarkdownBlock[] = []
    let inFaqSection = false

    for (let index = 0; index < blocks.length; index += 1) {
        const block = blocks[index]

        if (block.type === 'h2') {
            inFaqSection = block.text.trim().toLowerCase() === 'frequently asked questions'
            grouped.push(block)
            continue
        }

        const nextBlock = blocks[index + 1]
        if (inFaqSection && (block.type === 'h3' || block.type === 'h4') && nextBlock?.type === 'paragraph') {
            grouped.push({ type: 'faq', question: block.text, answer: nextBlock.text })
            index += 1
            continue
        }

        grouped.push(block)
    }

    return grouped
}

const journeyHighlights = {
    tenant: ['Verified homes', 'Direct landlord contact', 'Secure payment tracking'],
    landlord: ['Verified applicants', 'Simple property management', 'Clear rental records'],
    general: ['Verified people and properties', 'Direct communication', 'A clearer move-in journey'],
}

export default function HowItWorksPage() {
    const { user } = useAuth()
    const role = user?.role === 'landlord' ? 'landlord' : user?.role === 'tenant' ? 'tenant' : 'general'
    const markdownContent = role === 'landlord'
        ? landlordContent
        : role === 'tenant'
            ? tenantContent
            : howItWorksContent
    const blocks = useMemo(() => groupFaqBlocks(groupStepBlocks(parseMarkdown(markdownContent))), [markdownContent])
    const visibleBlocks = blocks.filter((block) => block.type !== 'h1')
    const isRoleGuide = role === 'tenant' || role === 'landlord'
    const roleLabel = role === 'landlord' ? 'For landlords' : role === 'tenant' ? 'For tenants' : 'The RentDirect way'
    const heroTitle = role === 'landlord'
        ? 'Turn your property into a better rental experience.'
        : role === 'tenant'
            ? 'Find a home with more clarity and confidence.'
            : 'A more considered way to rent.'
    const heroDescription = role === 'landlord'
        ? 'From your first listing to a completed tenancy, RentDirect keeps every important step visible and in your control.'
        : role === 'tenant'
            ? 'Discover verified properties, connect directly with landlords, and move in with a clear record of what happens next.'
            : 'RentDirect brings verified homes, people, payments, and rental progress into one calm, connected journey.'

    return (
        <div className="relative min-h-screen overflow-hidden bg-[#f8fafc] text-[#001e36]">
            <div className="pointer-events-none absolute right-[-18rem] top-[-10rem] h-[38rem] w-[38rem] rounded-full bg-orange-300/25 blur-[100px]" />
            <div className="pointer-events-none absolute bottom-[-20rem] left-[30%] h-[38rem] w-[38rem] rounded-full bg-yellow-200/35 blur-[120px]" />

            <section className="relative border-b border-slate-200/70">
                <div className="mx-auto max-w-7xl px-5 pb-16 pt-8 sm:px-8 md:pb-24 md:pt-10 lg:px-12">
                    {/* <div className="flex items-center justify-between">
                        <Link to="/" aria-label="RentDirect home">
                            <BrandLogo className="h-12 w-24 rounded-md bg-white p-1" />
                        </Link>
                        <span className="rounded-full border border-slate-300/80 bg-white/60 px-4 py-2 text-xs font-medium tracking-[0.12em] text-slate-600 backdrop-blur">
                            {roleLabel}
                        </span>
                    </div> */}

                    <div className="mt-20 grid items-end gap-12 lg:grid-cols-[1.15fr_0.85fr] lg:gap-20">
                        <div>
                            <p className="text-sm font-medium uppercase tracking-[0.28em] text-purple-800">How RentDirect works</p>
                            <h1 className="mt-6 font-semibold leading-[1.0] tracking-[-0.040em] lg:text-[2.8rem]">
                                {heroTitle}
                            </h1>
                            <p className="mt-8 max-w-2xl text-lg font-light leading-8 text-slate-600 md:text-xl">
                                {heroDescription}
                            </p>
                            <div className="mt-9 flex flex-wrap gap-3">
                                <Link to={role === 'landlord' && user?.id ? `/dashboard/landlord/${user.id}` : '/search'} className="inline-flex items-center rounded-full bg-[#001e36] px-6 py-3 text-sm font-medium text-white shadow-lg shadow-slate-900/10 transition hover:bg-slate-800">
                                    {role === 'landlord' ? 'Open dashboard' : 'Explore properties'}
                                </Link>
                                <Link to="/register" className="inline-flex items-center rounded-full border border-slate-300 bg-white/60 px-6 py-3 text-sm font-medium text-[#001e36] transition hover:border-slate-500 hover:bg-white">
                                    Create an account
                                </Link>
                            </div>
                        </div>

                        <div className="relative rounded-[2rem] border border-white/80 bg-white/75 p-6 shadow-[0_24px_80px_rgba(0,30,54,0.10)] backdrop-blur-md md:p-10">
                            <div className="flex items-center justify-between border-b border-slate-200 pb-5">
                                <span className="text-sm font-medium text-slate-500">Your journey, at a glance</span>
                                <span className="h-2.5 w-2.5 rounded-full bg-orange-500 shadow-[0_0_0_6px_rgba(249,115,22,0.12)]" />
                            </div>
                            <div className="space-y-3 pt-4">
                                {journeyHighlights[role].map((highlight, index) => (
                                    <div key={highlight} className="flex items-center gap-4">
                                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-600 via-blue-600 to-purple-700 text-xs font-medium text-white shadow-md shadow-indigo-900/20">
                                            {String(index + 1).padStart(2, '0')}
                                        </span>
                                        <span className="text-base font-medium text-slate-700">{highlight}</span>
                                    </div>
                                ))}
                            </div>
                            <div className="mt-8 rounded-2xl bg-purple-100 px-4 py-3 text-sm leading-6 text-blue-900">
                                One connected record from first conversation to move-in.
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            <main className="relative mx-auto grid max-w-7xl gap-10 px-5 py-14 sm:px-8 md:py-20 lg:grid-cols-[220px_1fr] lg:px-12">
                <aside className="hidden lg:block">
                    <div className="sticky top-8 border-l border-slate-300 pl-5">
                        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Inside this guide</p>
                        <p className="mt-4 text-sm leading-6 text-slate-600">A practical walkthrough of the RentDirect experience.</p>
                    </div>
                </aside>

                <article className="min-w-0">
                    <div className={`flex flex-col ${isRoleGuide ? 'gap-6' : 'gap-12'}`}>
                        {visibleBlocks.map((block, index) => {
                            if (block.type === 'h2') {
                                return (
                                    <div key={index} className="border-t border-slate-300 pt-8 first:border-t-0 first:pt-0">
                                        <h2 className="max-w-3xl text-3xl font-semibold tracking-[-0.035em] text-[#001e36] md:text-4xl">
                                            {renderInlineMarkdown(block.text)}
                                        </h2>
                                    </div>
                                )
                            }

                            if (block.type === 'step') {
                                const stepNumber = visibleBlocks
                                    .slice(0, index + 1)
                                    .filter((candidate) => candidate.type === 'step')
                                    .length
                                return (
                                    <section key={index} className="rounded-[1.75rem] border border-slate-200/90 bg-white/80 shadow-[0_16px_50px_rgba(0,30,54,0.06)] backdrop-blur-sm md:p-4">
                                        <div className="flex gap-2">
                                            <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-600 via-blue-600 to-purple-700 text-xl font-semibold text-white shadow-lg shadow-indigo-900/20">
                                                {String(stepNumber).padStart(2, '0')}
                                            </span>
                                            <div className="min-w-0 flex-1">
                                                <h3 className="text-2xl font-semibold tracking-[-0.02em] text-[#001e36] md:text-2xl px-6">
                                                    {renderInlineMarkdown(block.title)}
                                                </h3>
                                                <ul className="grid gap-2 md:grid-cols-1">
                                                    {block.items.map((item, itemIndex) => (
                                                        <li key={`${index}-${itemIndex}`} className="rounded-2xl bg-slate-50 px-6 py-1 leading-6 text-slate-600">
                                                            {renderInlineMarkdown(item)}
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                        </div>
                                    </section>
                                )
                            }

                            if (block.type === 'h3') {
                                return (
                                    <h3 key={index} className="text-2xl font-medium tracking-[-0.02em] text-[#001e36] md:text-3xl">
                                        {renderInlineMarkdown(block.text)}
                                    </h3>
                                )
                            }

                            if (block.type === 'h4') {
                                return (
                                    <h4 key={index} className="text-lg font-medium text-slate-700">
                                        {renderInlineMarkdown(block.text)}
                                    </h4>
                                )
                            }

                            if (block.type === 'faq') {
                                return (
                                    <div key={index} className="space-y-0">
                                        <h3 className="text-lg font-semibold leading-7 text-[#001e36]">
                                            {renderInlineMarkdown(block.question)}
                                        </h3>
                                        <p className="mt-0 text-lg font-light leading-8 text-slate-600">
                                            {renderInlineMarkdown(block.answer)}
                                        </p>
                                    </div>
                                )
                            }

                            if (block.type === 'list') {
                                return (
                                    <ul key={index} className="grid gap-3 md:grid-cols-2">
                                        {block.items.map((item, itemIndex) => (
                                            <li key={`${index}-${itemIndex}`} className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-3 text-base leading-7 text-slate-600">
                                                {renderInlineMarkdown(item)}
                                            </li>
                                        ))}
                                    </ul>
                                )
                            }

                            return (
                                <p key={index} className="max-w-5xl text-lg font-light leading-8 text-slate-600">
                                    {renderInlineMarkdown(block.text)}
                                </p>
                            )
                        })}
                    </div>
                </article>
            </main>
        </div>
    )
}
