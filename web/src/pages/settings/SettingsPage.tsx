import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useAuth } from '@/hooks/useAuth'
import DashboardBackButton from '@/components/DashboardBackButton'
import { api } from '@/lib/api'
import { buildFormDraftKey, readFormDraft, removeFormDraft, writeFormDraft } from '@/lib/formDrafts'
import {
    MOBILE_ERROR_MESSAGE,
    MOBILE_INPUT_PATTERN,
    MOBILE_INPUT_PLACEHOLDER,
    validateMobile,
    validateResidence,
} from '@/lib/profile'
import { User, UserResidence } from '@/types'

type GuarantorDetailsForm = {
    full_name: string
    relationship: string
    email: string
    mobile_number: string
    occupation: string
    employer: string
    residential_address: string
}

const emptyGuarantorDetails: GuarantorDetailsForm = {
    full_name: '',
    relationship: '',
    email: '',
    mobile_number: '',
    occupation: '',
    employer: '',
    residential_address: '',
}

type SettingsOtpPurpose = 'profile' | 'password' | 'account'
type AccountAction = 'freeze' | 'unfreeze' | 'delete'

type SettingsOtpChallenge = {
    purpose: SettingsOtpPurpose
    targetEmail: string
    action?: AccountAction
    freezeDuration?: number
}

type SettingsOtpRequestResponse = {
    purpose: SettingsOtpPurpose
    target_email: string
    expires_in_seconds: number
    message: string
}

type SettingsProfileDraft = {
    email?: string
    mobile?: string
    biodata?: Partial<{ first_name: string; middle_name: string; last_name: string }>
    residence?: Partial<UserResidence>
    guarantorDetails?: Partial<GuarantorDetailsForm>
}

function asRecord(value: unknown): Record<string, any> {
    return value && typeof value === 'object' && !Array.isArray(value)
        ? value as Record<string, any>
        : {}
}

function splitName(name?: string) {
    const parts = String(name || '').trim().split(/\s+/).filter(Boolean)
    return {
        first_name: parts[0] || '',
        middle_name: parts.length > 2 ? parts.slice(1, -1).join(' ') : '',
        last_name: parts.length > 1 ? parts[parts.length - 1] : '',
    }
}

function normalizeResidence(residence?: UserResidence | null): UserResidence {
    return {
        state: residence?.state || '',
        city: residence?.city || '',
        address: residence?.address || '',
        origin_country: residence?.origin_country || '',
        origin_city: residence?.origin_city || '',
    }
}

function normalizeGuarantorDetails(profile?: Record<string, any> | null): GuarantorDetailsForm {
    const guarantor = asRecord(asRecord(profile).guarantor_details)
    return {
        full_name: String(guarantor.full_name || ''),
        relationship: String(guarantor.relationship || ''),
        email: String(guarantor.email || ''),
        mobile_number: String(guarantor.mobile_number || ''),
        occupation: String(guarantor.occupation || ''),
        employer: String(guarantor.employer || ''),
        residential_address: String(guarantor.residential_address || ''),
    }
}

function buildGuarantorPayload(guarantor: GuarantorDetailsForm) {
    return {
        full_name: guarantor.full_name.trim(),
        relationship: guarantor.relationship.trim(),
        email: guarantor.email.trim(),
        mobile_number: guarantor.mobile_number.trim(),
        occupation: guarantor.occupation.trim(),
        employer: guarantor.employer.trim(),
        residential_address: guarantor.residential_address.trim(),
    }
}

function extractErrorMessage(error: any, fallback: string): string {
    if (typeof error?.response?.data === 'string') {
        return error.response.data
    }

    const detail = error?.response?.data?.detail
    if (detail) {
        return detail
    }

    const message = Object.values(error?.response?.data || {})
        .flat()
        .find(Boolean)

    return typeof message === 'string' ? message : error?.message || fallback
}

function Field({
    label,
    children,
}: {
    label: string
    children: React.ReactNode
}) {
    return (
        <div>
            <label className="form-label">{label}</label>
            {children}
        </div>
    )
}

export default function SettingsPage() {
    const { user, logout } = useAuth()
    const qc = useQueryClient()
    const { data: me, isLoading, isError } = useQuery({
        queryKey: ['users', 'me'],
        queryFn: async () => (await api.get<User>('/users/me')).data,
    })

    const [email, setEmail] = useState('')
    const [mobile, setMobile] = useState('')
    const [biodata, setBiodata] = useState({ first_name: '', middle_name: '', last_name: '' })
    const [residence, setResidence] = useState<UserResidence>(normalizeResidence())
    const [guarantorDetails, setGuarantorDetails] = useState<GuarantorDetailsForm>(emptyGuarantorDetails)
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
    const settingsProfileDraftStorageKey = useMemo(
        () => buildFormDraftKey('settings-profile', user?.id || user?.email),
        [user?.email, user?.id],
    )
    const [hydratedDraftStorageKey, setHydratedDraftStorageKey] = useState<string | null>(null)
    const [draftPersistenceEnabled, setDraftPersistenceEnabled] = useState(true)

    const [newPassword, setNewPassword] = useState('')
    const [confirmPassword, setConfirmPassword] = useState('')
    const [otpCode, setOtpCode] = useState('')
    const [otpChallenge, setOtpChallenge] = useState<SettingsOtpChallenge | null>(null)

    const [showAccountActionModal, setShowAccountActionModal] = useState(false)
    const [selectedFreezeDuration, setSelectedFreezeDuration] = useState<number | null>(null)
    const [accountFrozen, setAccountFrozen] = useState(false)

    const isLandlord = me?.role === 'landlord'

    useEffect(() => {
        if (!me) return

        const storedDraft = readFormDraft<SettingsProfileDraft>(settingsProfileDraftStorageKey)
        setEmail(storedDraft?.email ?? me.email ?? '')
        setMobile(storedDraft?.mobile ?? me.mobile ?? '')
        setResidence({
            ...normalizeResidence(me.residence),
            ...(storedDraft?.residence || {}),
        })

        const profile = me.role === 'landlord'
            ? asRecord(me.landlord_verification_profile)
            : asRecord(me.tenant_verification_profile)
        const nameParts = splitName(me.name)
        setBiodata({
            first_name: String(profile.first_name || nameParts.first_name),
            middle_name: String(profile.middle_name || nameParts.middle_name),
            last_name: String(profile.last_name || nameParts.last_name),
            ...(storedDraft?.biodata || {}),
        })
        setGuarantorDetails({
            ...normalizeGuarantorDetails(profile),
            ...(storedDraft?.guarantorDetails || {}),
        })
        setHydratedDraftStorageKey(settingsProfileDraftStorageKey)
        setAccountFrozen(Boolean(me.account_frozen))
    }, [me, settingsProfileDraftStorageKey])

    useEffect(() => {
        if (
            !draftPersistenceEnabled
            || !settingsProfileDraftStorageKey
            || hydratedDraftStorageKey !== settingsProfileDraftStorageKey
        ) {
            return
        }

        writeFormDraft(settingsProfileDraftStorageKey, {
            email,
            mobile,
            biodata,
            residence,
            guarantorDetails,
        })
    }, [
        biodata,
        draftPersistenceEnabled,
        email,
        guarantorDetails,
        hydratedDraftStorageKey,
        mobile,
        residence,
        settingsProfileDraftStorageKey,
    ])

    const validateProfile = () => {
        const nextErrors: Record<string, string> = {}
        const mobileError = validateMobile(mobile)
        const guarantorMobileError = validateMobile(guarantorDetails.mobile_number)

        if (mobileError) nextErrors.mobile = mobileError
        if (guarantorMobileError) nextErrors.guarantor_mobile_number = guarantorMobileError
        Object.assign(nextErrors, validateResidence('', residence))

        setFieldErrors(nextErrors)
        return Object.keys(nextErrors).length === 0
    }

    const buildProfilePayload = (): Record<string, any> => {
        const payload: Record<string, any> = {
            email: email.trim(),
            mobile: mobile.trim(),
            residence: {
                state: residence.state?.trim() || '',
                city: residence.city?.trim() || '',
                address: residence.address?.trim() || '',
                origin_country: residence.origin_country?.trim() || '',
                origin_city: residence.origin_city?.trim() || '',
            },
        }

        if (me?.role === 'tenant') {
            payload.guarantor_details = buildGuarantorPayload(guarantorDetails)
        }

        return payload
    }

    const closeOtpChallenge = () => {
        setOtpChallenge(null)
        setOtpCode('')
    }

    const requestSettingsOtp = useMutation({
        mutationFn: async ({ purpose, targetEmail }: SettingsOtpChallenge) => (
            await api.post<SettingsOtpRequestResponse>('/users/me/settings/request-otp', {
                purpose,
                target_email: targetEmail,
            })
        ).data,
        onSuccess: (response, challenge) => {
            setOtpCode('')
            setOtpChallenge({
                purpose: response.purpose,
                targetEmail: response.target_email,
                action: challenge.action,
                freezeDuration: challenge.freezeDuration,
            })
            alert(`Verification code sent to ${response.target_email}.`)
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to send a verification code.'))
        },
    })

    const saveProfile = useMutation({
        mutationFn: async (code: string) => {
            if (!validateProfile()) {
                throw new Error('Please fix the highlighted fields before saving.')
            }

            return (await api.post<User>('/users/me/settings', {
                ...buildProfilePayload(),
                otp_code: code,
            })).data
        },
        onSuccess: (nextUser) => {
            setDraftPersistenceEnabled(false)
            setHydratedDraftStorageKey(null)
            removeFormDraft(settingsProfileDraftStorageKey)
            qc.setQueryData(['users', 'me'], nextUser)
            localStorage.setItem('user', JSON.stringify(nextUser))
            closeOtpChallenge()
            alert('Settings updated successfully.')
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to update your settings.'))
        },
    })

    const changePassword = useMutation({
        mutationFn: async (code: string) => {
            if (!newPassword || !confirmPassword) {
                throw new Error('Fill in all password fields.')
            }
            if (newPassword !== confirmPassword) {
                throw new Error('New password and confirmation must match.')
            }

            await api.post('/users/me/password', {
                new_password: newPassword,
                otp_code: code,
            })
        },
        onSuccess: () => {
            setNewPassword('')
            setConfirmPassword('')
            closeOtpChallenge()
            alert('Password updated successfully.')
        },
        onError: (error) => {
            alert(extractErrorMessage(error, 'Unable to update your password.'))
        },
    })

    const freezeAccount = useMutation({
        mutationFn: async ({ duration, code }: { duration: number; code: string }) => (
            await api.post<User>('/users/me/freeze', { duration_months: duration, otp_code: code })
        ).data,
        onSuccess: (nextUser) => {
            qc.setQueryData(['users', 'me'], nextUser)
            localStorage.setItem('user', JSON.stringify(nextUser))
            setAccountFrozen(true)
            setSelectedFreezeDuration(null)
            closeOtpChallenge()
            alert('Account frozen successfully.')
        },
        onError: (error) => {
            alert('Failed to freeze account: ' + extractErrorMessage(error, 'Freeze failed'))
        },
    })

    const unfreezeAccount = useMutation({
        mutationFn: async (code: string) => (
            await api.delete<User>('/users/me/freeze', { data: { otp_code: code } })
        ).data,
        onSuccess: (nextUser) => {
            qc.setQueryData(['users', 'me'], nextUser)
            localStorage.setItem('user', JSON.stringify(nextUser))
            setAccountFrozen(false)
            closeOtpChallenge()
            alert('Account unfrozen successfully.')
        },
        onError: (error) => {
            alert('Failed to unfreeze account: ' + extractErrorMessage(error, 'Unfreeze failed'))
        },
    })

    const deleteAccount = useMutation({
        mutationFn: async (code: string) => {
            await api.delete('/users/me', { data: { otp_code: code } })
        },
        onSuccess: async () => {
            closeOtpChallenge()
            setShowAccountActionModal(false)
            await logout()
        },
        onError: (error) => {
            alert('Failed to delete account: ' + extractErrorMessage(error, 'Delete failed'))
        },
    })

    const dashboardPath = user?.role === 'landlord'
        ? `/dashboard/landlord/${user.id}`
        : user?.role === 'tenant'
            ? `/dashboard/tenant/${user.id}`
            : '/'

    const beginProfileVerification = () => {
        if (!me || !validateProfile()) return

        requestSettingsOtp.mutate({
            purpose: 'profile',
            targetEmail: email.trim().toLowerCase() || me.email,
        })
    }

    const beginPasswordVerification = () => {
        if (!me) return
        if (!newPassword || !confirmPassword) {
            alert('Fill in all password fields.')
            return
        }
        if (newPassword !== confirmPassword) {
            alert('New password and confirmation must match.')
            return
        }

        requestSettingsOtp.mutate({
            purpose: 'password',
            targetEmail: me.email,
        })
    }

    const beginAccountVerification = (action: AccountAction, freezeDuration?: number) => {
        if (!me) return

        setShowAccountActionModal(false)
        requestSettingsOtp.mutate({
            purpose: 'account',
            targetEmail: me.email,
            action,
            freezeDuration,
        })
    }

    const confirmOtpChallenge = () => {
        const normalizedCode = otpCode.trim().toUpperCase()
        if (!normalizedCode || !otpChallenge) {
            alert('Enter the verification code sent to your email.')
            return
        }

        if (otpChallenge.purpose === 'profile') {
            saveProfile.mutate(normalizedCode)
            return
        }
        if (otpChallenge.purpose === 'password') {
            changePassword.mutate(normalizedCode)
            return
        }
        if (otpChallenge.action === 'freeze' && otpChallenge.freezeDuration) {
            freezeAccount.mutate({ duration: otpChallenge.freezeDuration, code: normalizedCode })
            return
        }
        if (otpChallenge.action === 'unfreeze') {
            unfreezeAccount.mutate(normalizedCode)
            return
        }
        if (otpChallenge.action === 'delete') {
            deleteAccount.mutate(normalizedCode)
        }
    }

    const profileSavePending = requestSettingsOtp.isPending || saveProfile.isPending
    const accountActionPending = requestSettingsOtp.isPending || freezeAccount.isPending || unfreezeAccount.isPending || deleteAccount.isPending

    if (isLoading) {
        return (
            <div className="container-modern py-8">
                <div className="card p-6 text-gray-600">Loading settings...</div>
            </div>
        )
    }

    if (isError || !me) {
        return (
            <div className="container-modern py-8">
                <div className="card p-6">
                    <h1 className="text-2xl font-bold text-gray-900">Unable to load settings</h1>
                    <p className="mt-2 text-gray-600">Please refresh the page or sign in again.</p>
                </div>
            </div>
        )
    }

    return (
        <div className="container-modern py-8">
            <div className="mb-5">
                <DashboardBackButton fallbackTo={dashboardPath} />
            </div>

            <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                <div>
                    <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">Dashboard Settings</p>
                    <h1 className="text-3xl font-bold text-gray-900">Manage your account</h1>
                    <p className="mt-2 text-gray-600">Changes are saved only after OTP verification.</p>
                </div>
                <div className="flex flex-wrap gap-3">
                    <DashboardBackButton to={dashboardPath} label="Back to Dashboard" />
                    <Link to={`/profile/${me.id}`} className="btn btn-primary">Open Profile Page</Link>
                </div>
            </div>

            <div className="mt-8 grid items-stretch gap-6 md:grid-cols-2">
                <section className="card flex h-full flex-col p-6 md:col-span-2">
                    <div className="mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Biodata</h2>
                        <p className="mt-2 text-sm text-gray-600">Your verified name details are shown here.</p>
                    </div>
                    <div className="grid gap-5 md:grid-cols-3">
                        <Field label="First name">
                            <input className="form-input bg-gray-100 text-gray-500" value={biodata.first_name} readOnly />
                        </Field>
                        <Field label="Middle name">
                            <input className="form-input bg-gray-100 text-gray-500" value={biodata.middle_name} readOnly />
                        </Field>
                        <Field label="Last name">
                            <input className="form-input bg-gray-100 text-gray-500" value={biodata.last_name} readOnly />
                        </Field>
                    </div>
                </section>

                <section className="card flex h-full flex-col p-6">
                    <div className="mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Contact Details</h2>
                        <p className="mt-2 text-sm text-gray-600">Update your mobile number and email address.</p>
                    </div>
                    <div className="grid flex-1 gap-5">
                        <Field label="Email">
                            <input className="form-input" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="Enter your email" />
                        </Field>
                        <Field label="Mobile">
                            <input
                                className="form-input"
                                type="tel"
                                inputMode="tel"
                                pattern={MOBILE_INPUT_PATTERN}
                                maxLength={14}
                                title={MOBILE_ERROR_MESSAGE}
                                value={mobile}
                                onChange={e => setMobile(e.target.value)}
                                placeholder={MOBILE_INPUT_PLACEHOLDER}
                            />
                            {fieldErrors.mobile && <p className="form-error">{fieldErrors.mobile}</p>}
                        </Field>
                    </div>
                    <button className="btn btn-primary mt-6 w-full py-3" onClick={beginProfileVerification} disabled={profileSavePending}>
                        {profileSavePending ? 'Processing...' : 'Save Contact Details'}
                    </button>
                </section>

                <section className="card flex h-full flex-col p-6">
                    <div className="mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Password</h2>
                        <p className="mt-2 text-sm text-gray-600">Change your password with an OTP sent to your registered email.</p>
                    </div>
                    <div className="grid flex-1 gap-5">
                        <Field label="New password">
                            <input className="form-input" type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} placeholder="Enter new password" />
                        </Field>
                        <Field label="Confirm new password">
                            <input className="form-input" type="password" value={confirmPassword} onChange={e => setConfirmPassword(e.target.value)} placeholder="Confirm new password" />
                        </Field>
                    </div>
                    <button className="btn btn-primary mt-6 w-full py-3" onClick={beginPasswordVerification} disabled={requestSettingsOtp.isPending || changePassword.isPending}>
                        {requestSettingsOtp.isPending || changePassword.isPending ? 'Processing...' : 'Update Password'}
                    </button>
                </section>

                <section className="card flex h-full flex-col p-6">
                    <div className="mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Residence Address</h2>
                        <p className="mt-2 text-sm text-gray-600">Keep your current address up to date.</p>
                    </div>
                    <div className="grid flex-1 gap-5">
                        <div className="grid gap-5 sm:grid-cols-2">
                            <Field label="State">
                                <input className="form-input" value={residence.state || ''} onChange={e => setResidence(current => ({ ...current, state: e.target.value }))} placeholder="Enter residence state" />
                            </Field>
                            <Field label="City">
                                <input className="form-input" value={residence.city || ''} onChange={e => setResidence(current => ({ ...current, city: e.target.value }))} placeholder="Enter residence city" />
                            </Field>
                        </div>
                        <Field label="Street address">
                            <textarea className="form-input min-h-24" value={residence.address || ''} onChange={e => setResidence(current => ({ ...current, address: e.target.value }))} placeholder="Enter your full address" />
                            {fieldErrors.residence && <p className="form-error">{fieldErrors.residence}</p>}
                        </Field>
                    </div>
                    <button className="btn btn-primary mt-6 w-full py-3" onClick={beginProfileVerification} disabled={profileSavePending}>
                        {profileSavePending ? 'Processing...' : 'Save Residence Address'}
                    </button>
                </section>

                <section className="card flex h-full flex-col p-6">
                    <div className="mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Guarantor Details</h2>
                        <p className="mt-2 text-sm text-gray-600">Add or update your guarantor information. Every change requires OTP verification.</p>
                    </div>
                    {me.role === 'tenant' ? (
                        <>
                            <div className="grid flex-1 gap-5">
                                <div className="grid gap-5 sm:grid-cols-2">
                                    <Field label="Full name">
                                        <input className="form-input" value={guarantorDetails.full_name} onChange={e => setGuarantorDetails(current => ({ ...current, full_name: e.target.value }))} placeholder="Guarantor full name" />
                                    </Field>
                                    <Field label="Relationship">
                                        <input className="form-input" value={guarantorDetails.relationship} onChange={e => setGuarantorDetails(current => ({ ...current, relationship: e.target.value }))} placeholder="e.g. Parent, Sibling, Friend" />
                                    </Field>
                                </div>
                                <div className="grid gap-5 sm:grid-cols-2">
                                    <Field label="Email">
                                        <input className="form-input" type="email" value={guarantorDetails.email} onChange={e => setGuarantorDetails(current => ({ ...current, email: e.target.value }))} placeholder="guarantor@email.com" />
                                    </Field>
                                    <Field label="Mobile number">
                                        <input
                                            className="form-input"
                                            type="tel"
                                            inputMode="tel"
                                            pattern={MOBILE_INPUT_PATTERN}
                                            maxLength={14}
                                            title={MOBILE_ERROR_MESSAGE}
                                            value={guarantorDetails.mobile_number}
                                            onChange={e => setGuarantorDetails(current => ({ ...current, mobile_number: e.target.value }))}
                                            placeholder={MOBILE_INPUT_PLACEHOLDER}
                                        />
                                        {fieldErrors.guarantor_mobile_number && <p className="form-error">{fieldErrors.guarantor_mobile_number}</p>}
                                    </Field>
                                </div>
                                <div className="grid gap-5 sm:grid-cols-2">
                                    <Field label="Occupation">
                                        <input className="form-input" value={guarantorDetails.occupation} onChange={e => setGuarantorDetails(current => ({ ...current, occupation: e.target.value }))} placeholder="Occupation" />
                                    </Field>
                                    <Field label="Employer">
                                        <input className="form-input" value={guarantorDetails.employer} onChange={e => setGuarantorDetails(current => ({ ...current, employer: e.target.value }))} placeholder="Employer name" />
                                    </Field>
                                </div>
                                <Field label="Residential address">
                                    <textarea className="form-input min-h-20" value={guarantorDetails.residential_address} onChange={e => setGuarantorDetails(current => ({ ...current, residential_address: e.target.value }))} placeholder="Guarantor residential address" />
                                </Field>
                            </div>
                            <button className="btn btn-primary mt-6 w-full py-3" onClick={beginProfileVerification} disabled={profileSavePending}>
                                {profileSavePending ? 'Processing...' : 'Save Guarantor Details'}
                            </button>
                        </>
                    ) : (
                        <p className="text-sm text-gray-600">Guarantor details are available for tenant accounts.</p>
                    )}
                </section>

                <section className="card flex h-full flex-col p-6">
                    <div className="mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Freeze Account</h2>
                        <p className="mt-2 text-sm text-gray-600">
                            {isLandlord
                                ? 'Freeze your account after confirming an OTP. Frozen landlord accounts cannot list properties.'
                                : 'Account freezing is currently available to landlord accounts.'}
                        </p>
                    </div>
                    {isLandlord && (
                        accountFrozen ? (
                            <>
                                <p className="flex-1 rounded-lg border border-blue-200 bg-blue-50 p-4 text-sm text-blue-700">Your account is currently frozen.</p>
                                <button
                                    className="btn btn-outline mt-6 w-full py-3"
                                    onClick={() => beginAccountVerification('unfreeze')}
                                    disabled={accountActionPending}
                                >
                                    {accountActionPending ? 'Processing...' : 'Unfreeze Account'}
                                </button>
                            </>
                        ) : (
                            <button className="btn btn-outline mt-auto w-full py-3" onClick={() => setShowAccountActionModal(true)} disabled={accountActionPending}>
                                Freeze Account
                            </button>
                        )
                    )}
                </section>

                <section className="card flex h-full flex-col p-6">
                    <div className="mb-6">
                        <h2 className="text-2xl font-bold text-gray-900">Delete Account</h2>
                        <p className="mt-2 text-sm text-gray-600">Permanently remove your account after confirming an OTP.</p>
                    </div>
                    <button className="btn btn-danger mt-auto w-full py-3" onClick={() => setShowAccountActionModal(true)} disabled={accountActionPending}>
                        {deleteAccount.isPending ? 'Deleting...' : 'Delete Account'}
                    </button>
                </section>
            </div>

            {otpChallenge && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
                    <div className="mx-4 w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl">
                        <div className="mb-4">
                            <p className="text-sm font-medium uppercase tracking-[0.2em] text-blue-600">OTP Verification</p>
                            <h3 className="mt-2 text-2xl font-bold text-gray-900">
                                {otpChallenge.purpose === 'profile'
                                    ? 'Confirm settings update'
                                    : otpChallenge.purpose === 'password'
                                        ? 'Confirm password change'
                                        : 'Confirm account change'}
                            </h3>
                            <p className="mt-2 text-sm text-gray-600">
                                Enter the verification code sent to <span className="font-semibold text-gray-900">{otpChallenge.targetEmail}</span> before this change is saved.
                            </p>
                        </div>
                        <Field label="Verification code">
                            <input className="form-input" value={otpCode} onChange={e => setOtpCode(e.target.value.toUpperCase())} placeholder="Enter the 6-character code" maxLength={6} />
                        </Field>
                        <div className="mt-6 flex flex-wrap justify-end gap-3">
                            <button type="button" className="btn btn-outline" onClick={closeOtpChallenge} disabled={accountActionPending || profileSavePending || changePassword.isPending}>Cancel</button>
                            <button
                                type="button"
                                className="btn btn-outline"
                                onClick={() => requestSettingsOtp.mutate(otpChallenge)}
                                disabled={accountActionPending || profileSavePending || changePassword.isPending}
                            >
                                {requestSettingsOtp.isPending ? 'Sending...' : 'Resend OTP'}
                            </button>
                            <button
                                type="button"
                                className="btn btn-primary"
                                onClick={confirmOtpChallenge}
                                disabled={accountActionPending || profileSavePending || changePassword.isPending}
                            >
                                {saveProfile.isPending || changePassword.isPending || freezeAccount.isPending || unfreezeAccount.isPending || deleteAccount.isPending ? 'Verifying...' : 'Confirm'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {showAccountActionModal && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50">
                    <div className="mx-4 w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
                        <h3 className="text-xl font-bold text-gray-900">Account actions</h3>
                        <p className="mt-2 text-sm text-gray-600">Choose an action. An OTP will be required before it is persisted.</p>

                        {isLandlord && !accountFrozen && (
                            <div className="mt-6">
                                <h4 className="mb-3 text-sm font-semibold text-gray-900">Freeze duration</h4>
                                <div className="space-y-2">
                                    {[3, 6, 12].map(duration => (
                                        <label key={duration} className="flex cursor-pointer items-center rounded-lg border p-3 hover:bg-gray-50">
                                            <input type="radio" name="freezeDuration" value={duration} checked={selectedFreezeDuration === duration} onChange={() => setSelectedFreezeDuration(duration)} className="h-4 w-4 border-gray-300 text-blue-600 focus:ring-blue-500" />
                                            <span className="ml-3 text-sm font-medium text-gray-900">{duration} months</span>
                                        </label>
                                    ))}
                                </div>
                            </div>
                        )}

                        <div className="mt-6 flex flex-wrap gap-3">
                            <button className="btn btn-outline flex-1" onClick={() => { setShowAccountActionModal(false); setSelectedFreezeDuration(null) }}>Cancel</button>
                            {isLandlord && !accountFrozen && (
                                <button className="btn btn-outline flex-1" onClick={() => selectedFreezeDuration && beginAccountVerification('freeze', selectedFreezeDuration)} disabled={!selectedFreezeDuration || accountActionPending}>
                                    Freeze Instead
                                </button>
                            )}
                            <button className="btn btn-danger flex-1" onClick={() => beginAccountVerification('delete')} disabled={accountActionPending}>Delete</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
