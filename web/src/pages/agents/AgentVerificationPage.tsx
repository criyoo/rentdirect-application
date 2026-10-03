import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { HiCheckCircle, HiShieldCheck } from 'react-icons/hi'

import { useAppPopup } from '@/contexts/AppPopupContext'
import DashboardBackButton from '@/components/DashboardBackButton'
import LegalConsentCheckbox from '@/components/LegalConsentCheckbox'
import { api, extractApiErrorMessage } from '@/lib/api'
import { nigerianBanks } from '@/lib/banks'
import { getLegalDocumentBySlug } from '@/lib/legalDocuments'
import { nigeriaStateLgaMap, stateOfOriginOptions, worldCountryOptions } from '@/lib/locations'
import { AgentProfile, ServicePayment } from '@/types'

const GENDER_OPTIONS = ['Male', 'Female']

const INSPECTION_AGREEMENT_SLUG = 'physical-inspection-and-document-verification-agreement'

type AgentProfileFormState = {
    first_name: string
    middle_name: string
    last_name: string
    date_of_birth: string
    gender: string
    country_of_birth: string
    nationality: string
    state_of_origin: string
    lga_of_origin: string
    mobile: string
    whatsapp_number: string
    city: string
    residential_address: string
    nin_number: string
    bvn_number: string
    bank_name: string
    bank_code: string
    account_name: string
    account_number: string
}

const EMPTY_FORM: AgentProfileFormState = {
    first_name: '',
    middle_name: '',
    last_name: '',
    date_of_birth: '',
    gender: '',
    country_of_birth: '',
    nationality: 'Nigeria',
    state_of_origin: '',
    lga_of_origin: '',
    mobile: '',
    whatsapp_number: '',
    city: '',
    residential_address: '',
    nin_number: '',
    bvn_number: '',
    bank_name: '',
    bank_code: '',
    account_name: '',
    account_number: '',
}

export default function AgentVerificationPage() {
    const { alert, confirm } = useAppPopup()
    const navigate = useNavigate()
    const location = useLocation()
    const queryClient = useQueryClient()
    const [form, setForm] = useState<AgentProfileFormState>(EMPTY_FORM)
    const [formError, setFormError] = useState('')
    const [hasAcceptedInspectionAgreement, setHasAcceptedInspectionAgreement] = useState(false)
    const [registrationNoticeShown, setRegistrationNoticeShown] = useState(false)
    const [whatsappSameAsMobile, setWhatsappSameAsMobile] = useState(false)

    const { data: profile, isLoading } = useQuery({
        queryKey: ['agents', 'profile'],
        queryFn: async () => (await api.get<AgentProfile>('/agents/profile')).data,
    })

    useEffect(() => {
        const notice = (location.state as { registrationNotice?: string } | null)?.registrationNotice
        if (notice && !registrationNoticeShown) {
            setRegistrationNoticeShown(true)
            void alert(notice, { title: 'Welcome to RentDirect PIOs' })
            navigate(location.pathname, { replace: true, state: {} })
        }
    }, [alert, location.pathname, location.state, navigate, registrationNoticeShown])

    useEffect(() => {
        if (!profile) return
        setForm({
            first_name: profile.first_name || '',
            middle_name: profile.middle_name || '',
            last_name: profile.last_name || '',
            date_of_birth: profile.date_of_birth || '',
            gender: profile.gender || '',
            country_of_birth: profile.country_of_birth || '',
            nationality: profile.nationality || 'Nigeria',
            state_of_origin: profile.state_of_origin || '',
            lga_of_origin: profile.lga_of_origin || '',
            mobile: profile.mobile || '',
            whatsapp_number: profile.whatsapp_number || '',
            city: profile.city || '',
            residential_address: profile.residential_address || '',
            nin_number: profile.nin_number || '',
            bvn_number: profile.bvn_number || '',
            bank_name: profile.bank_name || '',
            bank_code: profile.bank_code || '',
            account_name: profile.account_name || '',
            account_number: profile.account_number || '',
        })
    }, [profile])

    const isVerified = profile?.verification_status === 'verified'
    const verificationPaymentRequired = Boolean(profile?.verification_payment_required)
    const verificationAttempts = profile?.verification_attempts ?? 0

    useEffect(() => {
        if (!whatsappSameAsMobile) return
        setForm((current) => (current.whatsapp_number === current.mobile ? current : { ...current, whatsapp_number: current.mobile }))
    }, [whatsappSameAsMobile, form.mobile])

    const saveProfile = useMutation({
        mutationFn: async (payload: AgentProfileFormState) =>
            (await api.patch<AgentProfile>('/agents/profile', payload)).data,
        onSuccess: async (saved) => {
            await queryClient.invalidateQueries({ queryKey: ['agents', 'profile'] })
            await queryClient.invalidateQueries({ queryKey: ['agents', 'dashboard'] })
            return saved
        },
    })

    const requestVerificationPayment = useMutation({
        mutationFn: async () =>
            (await api.post<ServicePayment>('/service-payments/request', { purpose: 'agent_verification' })).data,
        onSuccess: (payment) => {
            navigate(`/service-payments/${payment.id}`)
        },
        onError: async (error) => {
            await alert(extractApiErrorMessage(error, 'Unable to start the verification payment.'), { title: 'Payment', variant: 'warning' })
        },
    })

    const verifyIdentity = useMutation({
        mutationFn: async () => (await api.post<AgentProfile & { verification_payment?: ServicePayment | null }>('/agents/verify')).data,
        onSuccess: async (saved) => {
            await queryClient.invalidateQueries({ queryKey: ['agents', 'profile'] })
            await queryClient.invalidateQueries({ queryKey: ['agents', 'dashboard'] })
            const paymentId = saved?.verification_payment?.id
            if (paymentId) {
                navigate(`/service-payments/${paymentId}`)
                return
            }
            if (saved.mobile_warning) {
                await alert(saved.mobile_warning, { title: 'Verification complete', variant: 'warning' })
            } else {
                await alert('Your PIO identity has been verified.', { title: 'Verification complete' })
            }
        },
        onError: async (error) => {
            await alert(extractApiErrorMessage(error, 'Verification failed.'), { title: 'Verification', variant: 'warning' })
        },
    })

    const lgaOptions = useMemo(
        () => (form.state_of_origin ? nigeriaStateLgaMap[form.state_of_origin] || [] : []),
        [form.state_of_origin],
    )

    const updateField = (field: keyof AgentProfileFormState, value: string) => {
        setForm((current) => ({ ...current, [field]: value }))
    }

    const handleSave = async (event: React.FormEvent) => {
        event.preventDefault()
        setFormError('')
        try {
            await saveProfile.mutateAsync(form)
            await alert('Profile saved.', { title: 'PIO profile' })
        } catch (error) {
            setFormError(extractApiErrorMessage(error, 'Unable to save your profile.'))
        }
    }

    const handleVerify = async () => {
        setFormError('')
        if (!hasAcceptedInspectionAgreement) {
            setFormError('Please review and accept the Physical Inspection and Document Verification Agreement.')
            return
        }
        try {
            await saveProfile.mutateAsync(form)
            if (verificationPaymentRequired) {
                const proceed = await confirm(
                    'Your identity was verified. Complete the verification payment to activate your PIO account.',
                    { title: 'Verification payment', confirmLabel: 'Continue', cancelLabel: 'Cancel' },
                )
                if (!proceed) return
                await requestVerificationPayment.mutateAsync()
                return
            }
            if (verificationAttempts >= 3) {
                const proceed = await confirm(
                    'Your next attempts will attract extra fees of N100 for each attempt to cover verification cost',
                    { title: 'Extra Verification Fee', confirmLabel: 'Continue', cancelLabel: 'Cancel' },
                )
                if (!proceed) return
            }
            await verifyIdentity.mutateAsync()
        } catch {
            // Errors are surfaced via popup/form error already.
        }
    }

    if (isLoading) {
        return (
            <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50 flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-emerald-600 mx-auto"></div>
                    <p className="mt-4 text-gray-600">Loading PIO verification…</p>
                </div>
            </div>
        )
    }

    return (
        <div className="agent-theme min-h-screen bg-gradient-to-br from-emerald-50 via-white to-green-50">
            <div className="container-modern py-8">
                <div className="mb-5">
                    <DashboardBackButton to="/agents/dashboard" label="Back to dashboard" />
                </div>

                <div className="mb-6">
                    <h1 className="text-3xl font-bold text-gray-900">PIO Verification</h1>
                    <p className="mt-1 text-sm text-gray-600">
                        Complete your profile and verify your identity; the ₦500 verification fee is charged after a successful verification. There is no subscription for PIOs.
                    </p>
                </div>

                {isVerified && (
                    <div className="mb-8 flex items-center gap-3 rounded-xl border border-green-200 bg-green-50 p-4 text-green-900">
                        <HiCheckCircle className="h-6 w-6" />
                        <div>
                            <p className="font-semibold">
                                Your PIO account is verified.
                                {profile?.verification_badge && (
                                    <span className="ml-2 rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800">
                                        {profile.verification_badge}
                                    </span>
                                )}
                            </p>
                            <p className="text-sm">
                                You can now claim in-person inspection requests from your{' '}
                                <Link to="/agents/dashboard" className="font-semibold underline">PIO dashboard</Link>.
                            </p>
                        </div>
                    </div>
                )}

                <div className="grid gap-6 lg:grid-cols-3">
                    <form onSubmit={handleSave} className="card p-6 lg:col-span-2">
                        <div className="mb-4 flex items-center gap-2">
                            <HiShieldCheck className="h-6 w-6 text-emerald-600" />
                            <h2 className="text-xl font-semibold text-gray-900">Identity details</h2>
                        </div>

                        {formError && (
                            <div className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{formError}</div>
                        )}

                        <fieldset disabled={isVerified} className="space-y-4 disabled:opacity-80">
                            <div className="grid gap-4 sm:grid-cols-3">
                                <div>
                                    <label className="form-label" htmlFor="agent-first-name">First name</label>
                                    <input id="agent-first-name" className="form-input" required value={form.first_name} onChange={(e) => updateField('first_name', e.target.value)} />
                                </div>
                                <div>
                                    <label className="form-label" htmlFor="agent-middle-name">Middle name</label>
                                    <input id="agent-middle-name" className="form-input" value={form.middle_name} onChange={(e) => updateField('middle_name', e.target.value)} />
                                </div>
                                <div>
                                    <label className="form-label" htmlFor="agent-last-name">Last name</label>
                                    <input id="agent-last-name" className="form-input" required value={form.last_name} onChange={(e) => updateField('last_name', e.target.value)} />
                                </div>
                            </div>

                            <div className="grid gap-4 sm:grid-cols-3">
                                <div>
                                    <label className="form-label" htmlFor="agent-dob">Date of birth</label>
                                    <input id="agent-dob" type="date" className="form-input" required value={form.date_of_birth} onChange={(e) => updateField('date_of_birth', e.target.value)} />
                                </div>
                                <div>
                                    <label className="form-label" htmlFor="agent-gender">Gender</label>
                                    <select id="agent-gender" className="form-input" required value={form.gender} onChange={(e) => updateField('gender', e.target.value)}>
                                        <option value="">Select</option>
                                        {GENDER_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="form-label" htmlFor="agent-nationality">Nationality</label>
                                    <input id="agent-nationality" className="form-input" required value={form.nationality} onChange={(e) => updateField('nationality', e.target.value)} />
                                </div>
                            </div>

                            <div className="grid gap-4 sm:grid-cols-2">
                                <div>
                                    <label className="form-label" htmlFor="agent-country-of-birth">Country of birth</label>
                                    <select id="agent-country-of-birth" className="form-input" required value={form.country_of_birth} onChange={(e) => updateField('country_of_birth', e.target.value)}>
                                        <option value="">Select country of birth</option>
                                        {worldCountryOptions.map((country) => <option key={country} value={country}>{country}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="form-label" htmlFor="agent-city">City</label>
                                    <input id="agent-city" className="form-input" required placeholder="City of residence" value={form.city} onChange={(e) => updateField('city', e.target.value)} />
                                </div>
                            </div>

                            <div className="grid gap-4 sm:grid-cols-2">
                                <div>
                                    <label className="form-label" htmlFor="agent-state">State of origin</label>
                                    <select id="agent-state" className="form-input" required value={form.state_of_origin} onChange={(e) => updateField('state_of_origin', e.target.value)}>
                                        <option value="">Select state</option>
                                        {stateOfOriginOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="form-label" htmlFor="agent-lga">LGA of origin</label>
                                    {lgaOptions.length > 0 ? (
                                        <select id="agent-lga" className="form-input" required value={form.lga_of_origin} onChange={(e) => updateField('lga_of_origin', e.target.value)}>
                                            <option value="">Select LGA</option>
                                            {lgaOptions.map((option) => <option key={option} value={option}>{option}</option>)}
                                        </select>
                                    ) : (
                                        <input id="agent-lga" className="form-input" required value={form.lga_of_origin} onChange={(e) => updateField('lga_of_origin', e.target.value)} />
                                    )}
                                </div>
                            </div>

                            <div className="grid gap-4 sm:grid-cols-2">
                                <div>
                                    <label className="form-label" htmlFor="agent-mobile">Mobile number</label>
                                    <input id="agent-mobile" className="form-input" required placeholder="08012345678" value={form.mobile} onChange={(e) => updateField('mobile', e.target.value)} />
                                </div>
                                <div>
                                    <label className="form-label" htmlFor="agent-whatsapp">WhatsApp number</label>
                                    <input
                                        id="agent-whatsapp"
                                        className="form-input disabled:bg-gray-100 disabled:text-gray-500"
                                        placeholder="08012345678"
                                        value={form.whatsapp_number}
                                        disabled={whatsappSameAsMobile}
                                        onChange={(e) => updateField('whatsapp_number', e.target.value)}
                                    />
                                    <label className="mt-2 flex items-center gap-2 text-sm text-gray-600">
                                        <input
                                            type="checkbox"
                                            className="h-4 w-4 rounded border-gray-300 text-emerald-600 accent-emerald-600"
                                            checked={whatsappSameAsMobile}
                                            onChange={(e) => {
                                                setWhatsappSameAsMobile(e.target.checked)
                                                if (e.target.checked) updateField('whatsapp_number', form.mobile)
                                            }}
                                        />
                                        Same as mobile number?
                                    </label>
                                </div>
                            </div>

                            <div>
                                <label className="form-label" htmlFor="agent-address">Full residential address</label>
                                <input id="agent-address" className="form-input" required value={form.residential_address} onChange={(e) => updateField('residential_address', e.target.value)} />
                            </div>

                            <div className="grid gap-4 sm:grid-cols-2">
                                <div>
                                    <label className="form-label" htmlFor="agent-nin">NIN (11 digits)</label>
                                    <input id="agent-nin" className="form-input" required inputMode="numeric" maxLength={11} value={form.nin_number} onChange={(e) => updateField('nin_number', e.target.value.replace(/\D/g, ''))} />
                                </div>
                                <div>
                                    <label className="form-label" htmlFor="agent-bvn">BVN (11 digits)</label>
                                    <input id="agent-bvn" className="form-input" required inputMode="numeric" maxLength={11} value={form.bvn_number} onChange={(e) => updateField('bvn_number', e.target.value.replace(/\D/g, ''))} />
                                </div>
                            </div>

                            <h3 className="pt-2 text-lg font-semibold text-gray-900">Payout bank details</h3>
                            <div className="grid gap-4 sm:grid-cols-3">
                                <div>
                                    <label className="form-label" htmlFor="agent-bank">Bank name</label>
                                    <select id="agent-bank" className="form-input" required value={form.bank_name} onChange={(e) => updateField('bank_name', e.target.value)}>
                                        <option value="">Select bank</option>
                                        {nigerianBanks.map((bank) => <option key={bank} value={bank}>{bank}</option>)}
                                    </select>
                                </div>
                                <div>
                                    <label className="form-label" htmlFor="agent-account-name">Account name</label>
                                    <input id="agent-account-name" className="form-input" required value={form.account_name} onChange={(e) => updateField('account_name', e.target.value.replace(/[^A-Za-z\s'\-.]/g, ''))} />
                                </div>
                                <div>
                                    <label className="form-label" htmlFor="agent-account-number">Account number (10 digits)</label>
                                    <input id="agent-account-number" className="form-input" required inputMode="numeric" maxLength={10} value={form.account_number} onChange={(e) => updateField('account_number', e.target.value.replace(/\D/g, ''))} />
                                </div>
                            </div>
                        </fieldset>
                    </form>

                    <div className="space-y-6">
                        {!isVerified && (
                            <div className="card p-6">
                                <h2 className="mb-3 text-xl font-semibold text-gray-900">Final step</h2>
                                <LegalConsentCheckbox
                                    id="agent-inspection-agreement"
                                    documents={[
                                        {
                                            slug: INSPECTION_AGREEMENT_SLUG,
                                            title: getLegalDocumentBySlug(INSPECTION_AGREEMENT_SLUG)?.title || 'Physical Inspection and Document Verification Agreement',
                                        },
                                    ]}
                                    checked={hasAcceptedInspectionAgreement}
                                    onChange={setHasAcceptedInspectionAgreement}
                                    consentContext="your PIO registration"
                                />
                                <button
                                    type="button"
                                    onClick={handleVerify}
                                    disabled={requestVerificationPayment.isPending || verifyIdentity.isPending || saveProfile.isPending}
                                    className="btn btn-primary mt-4 w-full py-3 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                    {requestVerificationPayment.isPending ? 'Starting…' : verifyIdentity.isPending ? 'Verifying…' : 'Verify my identity'}
                                </button>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
