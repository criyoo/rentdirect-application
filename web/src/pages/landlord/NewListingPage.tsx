import { Link } from 'react-router-dom'
import {
    HiHome,
    HiOfficeBuilding,
    HiMoon,
    HiArrowRight,
    HiShieldCheck,
    HiUserGroup,
    HiChatAlt2,
    HiCash,
    HiChartBar,
    HiClipboardCheck,
} from 'react-icons/hi'
import DashboardBackButton from '@/components/DashboardBackButton'
import { useAuth } from '@/hooks/useAuth'

const listingCategories = [
    {
        category: 'residential',
        title: 'Residential Property',
        summary: 'Long-term homes rented on a yearly basis. Best for flats, duplexes and family houses in estates or neighbourhoods across Nigeria.',
        examples: ['Flats & apartments', 'Duplexes & detached houses', 'Studios & townhouses'],
        icon: HiHome,
        accent: 'bg-blue-900/10 text-blue-900',
    },
    {
        category: 'commercial',
        title: 'Commercial Property',
        summary: 'Spaces for business use — offices, shops and warehouses in commercial districts, plazas and industrial areas.',
        examples: ['Offices & co-working floors', 'Shops & retail spaces', 'Warehouses & industrial units'],
        icon: HiOfficeBuilding,
        accent: 'bg-amber-500/15 text-amber-700',
    },
    {
        category: 'shortlet',
        title: 'Shortlets',
        summary: 'Furnished stays booked per night — serviced apartments and holiday-style rentals popular in Lagos, Abuja and Port Harcourt.',
        examples: ['Serviced apartments', 'Short-stay studios', 'Vacation duplexes & villas'],
        icon: HiMoon,
        accent: 'bg-emerald-600/10 text-emerald-700',
    },
] as const

const listingBenefits = [
    {
        title: 'Reach verified tenants',
        copy: 'Connect with identity-verified renters who are actively searching.',
        icon: HiUserGroup,
    },
    {
        title: 'Build trust faster',
        copy: 'Property and ownership verification improves your credibility.',
        icon: HiShieldCheck,
    },
    {
        title: 'Direct communication',
        copy: 'Speak to prospective tenants without unnecessary middlemen.',
        icon: HiChatAlt2,
    },
    {
        title: 'Secure payment records',
        copy: 'Track deposits, rent payments, receipts, and payouts in one place.',
        icon: HiCash,
    },
    {
        title: 'More visibility',
        copy: 'Feature eligible listings across search and discovery pages.',
        icon: HiChartBar,
    },
    {
        title: 'Simpler rental management',
        copy: 'Manage enquiries, agreements, checklists, and renewal reminders.',
        icon: HiClipboardCheck,
    },
] as const

export default function NewListingPage() {
    const { user } = useAuth()

    return (
        <div className="min-h-screen bg-[#0d1b3e] py-12">
            <div className="max-w-6xl mx-auto px-4">
                <DashboardBackButton
                    to={user ? `/dashboard/landlord/${user.id}` : '/'}
                    label="Back to Dashboard"
                    className="border-white/20 bg-white/10 text-white hover:text-amber-300"
                />

                <div className="mt-8 text-center">
                    <p className="text-sm font-semibold uppercase tracking-[0.2em] text-amber-400">
                        New Listing
                    </p>
                    <h1 className="mt-3 text-3xl md:text-4xl font-bold text-white">
                        What kind of property are you listing?
                    </h1>
                    <p className="mt-3 text-base text-blue-100/80 max-w-2xl mx-auto">
                        Choose a category so we can collect the right details — pricing, stay rules and
                        verification requirements differ for each one.
                    </p>
                </div>

                <div className="mt-12 grid grid-cols-1 gap-6 md:grid-cols-3">
                    {listingCategories.map(({ category, title, summary, examples, icon: Icon, accent }) => (
                        <Link
                            key={category}
                            to={`/listings/new/${category}`}
                            className="group flex flex-col rounded-2xl border border-white/10 bg-white/[0.06] p-7 backdrop-blur transition duration-200 hover:-translate-y-1 hover:border-amber-400/60 hover:bg-white/[0.09] hover:shadow-2xl hover:shadow-black/40 focus:outline-none focus:ring-2 focus:ring-amber-400"
                            aria-label={`Create a ${title} listing`}
                        >
                            <div className={`flex h-12 w-12 items-center justify-center rounded-xl ${accent}`}>
                                <Icon className="h-6 w-6" />
                            </div>
                            <h2 className="mt-5 text-xl font-bold text-white">{title}</h2>
                            <p className="mt-2 text-sm leading-relaxed text-blue-100/75">{summary}</p>
                            <ul className="mt-4 space-y-1.5 text-sm text-blue-100/60">
                                {examples.map((example) => (
                                    <li key={example} className="flex items-center gap-2">
                                        <span className="h-1 w-1 rounded-full bg-amber-400" />
                                        {example}
                                    </li>
                                ))}
                            </ul>
                            <span className="mt-auto inline-flex items-center gap-2 pt-6 text-sm font-semibold text-amber-300 transition group-hover:gap-3">
                                Continue
                                <HiArrowRight className="h-4 w-4" />
                            </span>
                        </Link>
                    ))}
                </div>

                <div className="mt-20">
                    <div className="text-center">
                        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-amber-400">
                            Why list with us?
                        </p>
                        <h2 className="mt-3 text-2xl md:text-3xl font-bold text-white">
                            Benefits of listing your property with RentDirect
                        </h2>
                        <p className="mt-3 text-base text-blue-100/80 max-w-2xl mx-auto">
                            Avoid disputes with trusted tenants, transparent payments, and less admin — everything you need
                            to let your property with confidence.
                        </p>
                    </div>

                    <div className="mx-auto mt-10 max-w-3xl space-y-3">
                        {listingBenefits.map(({ title, copy, icon: Icon }) => (
                            <div
                                key={title}
                                className="flex items-center gap-4 rounded-xl border border-white/10 bg-white/[0.06] px-5 py-4 backdrop-blur"
                            >
                                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-amber-500/15 text-amber-400">
                                    <Icon className="h-5 w-5" />
                                </div>
                                <div className="min-w-0">
                                    <h3 className="text-sm font-semibold text-white">{title}</h3>
                                    <p className="mt-0.5 text-sm leading-relaxed text-blue-100/70">{copy}</p>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    )
}
