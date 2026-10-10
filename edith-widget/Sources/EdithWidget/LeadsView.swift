import SwiftUI
import AppKit

@MainActor
final class LeadsModel: ObservableObject {
    @Published var leads: [StartupLead] = []
    @Published var count: Int = 10
    @Published var countries: Set<String> = Set(UserDefaults.standard.stringArray(forKey: "leadsCountries") ?? []) {
        didSet { UserDefaults.standard.set(Array(countries).sorted(), forKey: "leadsCountries") }
    }

    var location: String { Countries.ordered.filter(countries.contains).joined(separator: ", ") }

    var locationLabel: String {
        let picked = Countries.ordered.filter(countries.contains)
        guard let first = picked.first else { return "Anywhere" }
        return picked.count == 1 ? first : "\(first) +\(picked.count - 1)"
    }

    func toggle(country: String) {
        if countries.contains(country) { countries.remove(country) } else { countries.insert(country) }
    }

    func toggle(region: [String]) {
        if region.allSatisfy(countries.contains) { countries.subtract(region) } else { countries.formUnion(region) }
    }
    @Published var isSearching = false
    @Published var message: String = ""
    @Published var error: String?
    @Published var copiedID: String?
    @Published var composingID: Int?
    @Published var busyIDs: Set<Int> = []

    static let counts = [5, 10, 20, 30]

    enum EarlierFilter: String, CaseIterable {
        case all = "All", toEmail = "To email", emailed = "Emailed"
    }

    @Published var earlierFilter: EarlierFilter = .all
    @Published var isRefreshing = false
    @Published var latestIDs: [Int] = UserDefaults.standard.array(forKey: "leadsLatestIDs") as? [Int] ?? [] {
        didSet { UserDefaults.standard.set(latestIDs, forKey: "leadsLatestIDs") }
    }

    var latest: [StartupLead] {
        let byID = Dictionary(leads.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        return latestIDs.compactMap { byID[$0] }
    }

    var earlier: [StartupLead] { earlier(earlierFilter) }

    func earlier(_ filter: EarlierFilter) -> [StartupLead] {
        let skip = Set(latestIDs)
        return leads.filter { lead in
            guard !skip.contains(lead.id) else { return false }
            let emailed = !lead.sentRecipients.isEmpty || lead.status == "contacted"
            switch filter {
            case .all: return true
            case .toEmail: return !emailed && lead.status == "delivered"
            case .emailed: return emailed
            }
        }
    }

    func count(for filter: EarlierFilter) -> Int { earlier(filter).count }

    private let client = BackendClient()
    private var loaded = false

    func loadIfNeeded() {
        guard !loaded else { return }
        loaded = true
        refresh()
    }

    func refresh() {
        guard !isRefreshing else { return }
        isRefreshing = true
        Task {
            defer { isRefreshing = false }
            guard await ensureServer() else { return }
            do {
                async let delivered = client.startupLeads(status: "delivered", limit: 200)
                async let contacted = client.startupLeads(status: "contacted", limit: 200)
                let all = try await delivered + contacted
                var seen = Set<Int>()
                leads = all.filter { seen.insert($0.id).inserted }
                    .sorted { ($0.deliveredAt ?? "") > ($1.deliveredAt ?? "") }
                if leads.isEmpty { message = "Pick how many and tap Find." }
                error = nil
            } catch {
                loaded = false
                self.error = Self.describe(error)
            }
        }
    }

    func find() {
        guard !isSearching else { return }
        isSearching = true
        error = nil
        let place = location.trimmingCharacters(in: .whitespaces)
        message = place.isEmpty ? "Searching VC portfolios… first run takes about a minute" : "Finding AI startups in \(place)…"
        Task {
            defer { isSearching = false }
            guard await ensureServer() else { return }
            do {
                let result = try await client.findStartups(count: count, location: place.isEmpty ? nil : place)
                let newIDs = Set(result.leads.map(\.id))
                leads = result.leads + leads.filter { !newIDs.contains($0.id) }
                if !result.leads.isEmpty { latestIDs = result.leads.map(\.id) }
                if let warnings = result.warnings, !warnings.isEmpty {
                    error = warnings.joined(separator: " · ") + " — some leads have no email; top up credits to find more."
                }
                message = result.returned == 0
                    ? "No new leads right now — try again later."
                    : "\(result.returned) new\(place.isEmpty ? "" : " in \(place)") · \(result.remainingPool) more in the pool"
            } catch {
                message = ""
                self.error = Self.describe(error)
            }
        }
    }

    func mark(_ lead: StartupLead, _ status: String) {
        guard let index = leads.firstIndex(where: { $0.id == lead.id }) else { return }
        let previous = leads[index].status
        leads[index].status = status
        Task {
            do {
                try await client.updateStartupLead(id: lead.id, status: status)
            } catch {
                if let i = leads.firstIndex(where: { $0.id == lead.id }) { leads[i].status = previous }
                self.error = Self.describe(error)
            }
        }
    }

    func compose(_ lead: StartupLead) {
        if composingID == lead.id {
            composingID = nil
            return
        }
        composingID = lead.id
        guard lead.draftBody == nil else { return }
        regenerate(lead)
    }

    func regenerate(_ lead: StartupLead) {
        guard !busyIDs.contains(lead.id) else { return }
        busyIDs.insert(lead.id)
        Task {
            defer { busyIDs.remove(lead.id) }
            do {
                let drafted = try await client.draftStartupEmail(id: lead.id)
                replace(drafted)
                if drafted.draftTo == nil, let warnings = drafted.warnings, !warnings.isEmpty {
                    error = warnings.joined(separator: " · ") + " — no email found for \(drafted.company)."
                }
            } catch {
                self.error = Self.describe(error)
            }
        }
    }

    func send(_ lead: StartupLead, to: [String], subject: String, body: String) {
        guard !busyIDs.contains(lead.id) else { return }
        busyIDs.insert(lead.id)
        error = nil
        Task {
            defer { busyIDs.remove(lead.id) }
            do {
                replace(try await client.sendStartupEmail(id: lead.id, to: to, subject: subject, body: body))
                composingID = nil
                message = to.count == 1 ? "Sent to \(to[0])" : "Sent to \(to.count) people"
            } catch {
                self.error = Self.describe(error)
            }
        }
    }

    private func replace(_ lead: StartupLead) {
        if let i = leads.firstIndex(where: { $0.id == lead.id }) { leads[i] = lead }
    }

    func copy(_ text: String, id: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        copiedID = id
        Task {
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            if copiedID == id { copiedID = nil }
        }
    }

    private func ensureServer() async -> Bool {
        if ServerLauncher.shared.isLocal, !(await ServerLauncher.shared.ensureRunning()) {
            error = "Couldn't start Eddy's local server — see ~/.edith/server.log"
            return false
        }
        return true
    }

    private static func describe(_ error: Error) -> String {
        if let backendError = error as? BackendError {
            switch backendError {
            case .noToken: return "No API token configured"
            case .http(let code, let message): return "\(message) (\(code))"
            }
        }
        if (error as? URLError)?.code == .timedOut { return "Search timed out — try again" }
        return error.localizedDescription
    }
}

struct LeadsView: View {
    @ObservedObject var model: LeadsModel
    let accent: Color
    @State private var showingCountries = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            controls
            if let error = model.error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 11))
                    .foregroundStyle(.red.opacity(0.85))
            } else if !model.message.isEmpty {
                HStack(spacing: 6) {
                    if model.isSearching { ProgressView().controlSize(.mini).tint(.white) }
                    Text(model.message)
                        .font(.system(size: 11))
                        .foregroundStyle(.white.opacity(0.45))
                }
            }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 8, pinnedViews: [.sectionHeaders]) {
                    if !model.latest.isEmpty {
                        Section {
                            ForEach(model.latest) { lead in
                                LeadCard(lead: lead, model: model, accent: accent)
                            }
                        } header: {
                            sectionHeader("Latest", count: model.latest.count)
                        }
                    }
                    Section {
                        ForEach(model.earlier) { lead in
                            LeadCard(lead: lead, model: model, accent: accent)
                        }
                        if model.earlier.isEmpty {
                            Text(model.earlierFilter == .all ? "Nothing older yet." : "No leads here.")
                                .font(.system(size: 11))
                                .foregroundStyle(.white.opacity(0.35))
                                .padding(.vertical, 6)
                        }
                    } header: {
                        earlierHeader
                    }
                }
            }
            .scrollIndicators(.never)
            .frame(maxHeight: .infinity)
        }
        .onAppear { model.loadIfNeeded() }
    }

    private func sectionHeader(_ title: String, count: Int) -> some View {
        HStack(spacing: 6) {
            Text(title.uppercased())
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(.white.opacity(0.55))
            Text("\(count)")
                .font(.system(size: 10, weight: .semibold, design: .rounded))
                .foregroundStyle(.white.opacity(0.35))
            Spacer()
        }
        .padding(.vertical, 5)
        .frame(maxWidth: .infinity)
        .background(Color.black)
    }

    private var earlierHeader: some View {
        HStack(spacing: 5) {
            Text(model.latest.isEmpty ? "ALL LEADS" : "EARLIER")
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(.white.opacity(0.55))
            Spacer(minLength: 4)
            ForEach(LeadsModel.EarlierFilter.allCases, id: \.self) { filter in
                let on = model.earlierFilter == filter
                Button { model.earlierFilter = filter } label: {
                    Text("\(filter.rawValue) \(model.count(for: filter))")
                        .font(.system(size: 10, weight: on ? .semibold : .regular))
                        .foregroundStyle(on ? .black : .white.opacity(0.6))
                        .padding(.horizontal, 7)
                        .frame(height: 18)
                        .background(on ? Color.white : Color.white.opacity(0.08), in: Capsule())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.vertical, 5)
        .frame(maxWidth: .infinity)
        .background(Color.black)
    }

    private var controls: some View {
        HStack(spacing: 6) {
            ForEach(LeadsModel.counts, id: \.self) { n in
                Button("\(n)") { model.count = n }
                    .buttonStyle(.plain)
                    .font(.system(size: 11.5, weight: .semibold, design: .rounded))
                    .foregroundStyle(model.count == n ? .black : .white.opacity(0.7))
                    .frame(width: 34, height: 26)
                    .background(model.count == n ? Color.white : Color.white.opacity(0.08), in: Capsule())
            }
            Button { showingCountries.toggle() } label: {
                HStack(spacing: 4) {
                    Image(systemName: "mappin")
                        .font(.system(size: 10))
                    Text(model.locationLabel)
                        .font(.system(size: 11.5, weight: model.countries.isEmpty ? .regular : .semibold))
                        .lineLimit(1)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 8, weight: .bold))
                }
                .foregroundStyle(model.countries.isEmpty ? .white.opacity(0.6) : .black)
                .padding(.horizontal, 9)
                .frame(height: 26)
                .background(model.countries.isEmpty ? Color.white.opacity(0.08) : accent, in: Capsule())
            }
            .buttonStyle(.plain)
            .help(model.countries.isEmpty ? "Pick countries — empty searches all of Europe + Middle East" : model.location)
            .popover(isPresented: $showingCountries, arrowEdge: .bottom) {
                CountryPicker(model: model, accent: accent)
            }
            Button(action: model.refresh) {
                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.white.opacity(0.7))
                    .rotationEffect(.degrees(model.isRefreshing ? 360 : 0))
                    .animation(model.isRefreshing ? .linear(duration: 0.8).repeatForever(autoreverses: false) : .default, value: model.isRefreshing)
                    .frame(width: 26, height: 26)
                    .background(Color.white.opacity(0.08), in: Circle())
            }
            .buttonStyle(.plain)
            .help("Refresh leads")
            Spacer(minLength: 4)
            Button(action: model.find) {
                HStack(spacing: 5) {
                    Image(systemName: model.isSearching ? "hourglass" : "sparkle.magnifyingglass")
                    Text(model.isSearching ? "Finding…" : "Find \(model.count)")
                }
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(.black)
                .padding(.horizontal, 12)
                .frame(height: 26)
                .background(model.isSearching ? Color.white.opacity(0.5) : accent, in: Capsule())
            }
            .buttonStyle(.plain)
            .disabled(model.isSearching)
            .help("Find \(model.count) new startups to apply to or DM")
        }
    }
}

private struct LeadCard: View {
    let lead: StartupLead
    @ObservedObject var model: LeadsModel
    let accent: Color

    private var done: Bool { ["contacted", "applied", "interview", "skipped", "rejected"].contains(lead.status) }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Text(lead.isRole ? "ROLE" : "DM")
                    .font(.system(size: 9, weight: .bold, design: .rounded))
                    .foregroundStyle(.black)
                    .padding(.horizontal, 5)
                    .frame(height: 15)
                    .background(lead.isRole ? Color(red: 0.35, green: 0.9, blue: 0.6) : Color(red: 1.0, green: 0.78, blue: 0.3), in: Capsule())
                Text(lead.company)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.white)
                    .lineLimit(1)
                if let fund = lead.fund {
                    Text(fund)
                        .font(.system(size: 10))
                        .foregroundStyle(.white.opacity(0.35))
                        .lineLimit(1)
                }
                Spacer(minLength: 4)
                Text("\(Int(lead.score))")
                    .font(.system(size: 10, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white.opacity(0.5))
            }
            if let role = lead.roleTitle, lead.isRole {
                Text(role + (lead.salary.map { " · \($0)" } ?? ""))
                    .font(.system(size: 11.5))
                    .foregroundStyle(.white.opacity(0.8))
                    .lineLimit(2)
            }
            if let reasons = lead.reasons, !reasons.isEmpty {
                Text(reasons.prefix(3).joined(separator: " · "))
                    .font(.system(size: 10.5))
                    .foregroundStyle(.white.opacity(0.4))
                    .lineLimit(1)
            }
            if let facts = lead.companyInfo?.summary, !facts.isEmpty {
                Text(facts)
                    .font(.system(size: 10.5, weight: .medium))
                    .foregroundStyle(accent.opacity(0.9))
                    .lineLimit(1)
            }
            ForEach(Array(lead.contacts.prefix(3).enumerated()), id: \.offset) { _, person in
                ContactRow(person: person, model: model, leadID: lead.id)
            }
            if let pitch = lead.pitch {
                Text(pitch)
                    .font(.system(size: 11))
                    .italic()
                    .foregroundStyle(.white.opacity(0.7))
                    .lineLimit(3)
                    .textSelection(.enabled)
            }
            actions
            if model.composingID == lead.id {
                EmailComposer(lead: lead, model: model, accent: accent)
            }
        }
        .padding(10)
        .background(Color.white.opacity(done ? 0.03 : 0.06), in: RoundedRectangle(cornerRadius: 12))
        .opacity(done ? 0.5 : 1)
    }

    private var actions: some View {
        HStack(spacing: 5) {
            if let link = lead.link {
                chip("arrow.up.right", lead.isRole ? "Apply" : "Site") { NSWorkspace.shared.open(link) }
            }
            if let linkedin = lead.companyLinkedin {
                chip("building.2", "LinkedIn") { NSWorkspace.shared.open(linkedin) }
            }
            if !lead.sentRecipients.isEmpty {
                chip("checkmark.circle", "Sent \(lead.sentRecipients.count)") { model.compose(lead) }
                    .help(lead.sentRecipients.sorted().joined(separator: ", "))
            } else {
                chip(model.composingID == lead.id ? "chevron.up" : "square.and.pencil", "Email") { model.compose(lead) }
                    .help(lead.draftTo ?? lead.bestEmail ?? "No email found yet")
            }
            Spacer(minLength: 0)
            if done {
                Text(lead.status)
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(.white.opacity(0.5))
            } else {
                iconChip("checkmark", help: "Mark contacted") { model.mark(lead, "contacted") }
                iconChip("xmark", help: "Skip") { model.mark(lead, "skipped") }
            }
        }
        .padding(.top, 2)
    }

    private func chip(_ symbol: String, _ label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 3) {
                Image(systemName: symbol)
                Text(label)
            }
            .font(.system(size: 10, weight: .medium))
            .foregroundStyle(.white.opacity(0.8))
            .padding(.horizontal, 7)
            .frame(height: 20)
            .background(Color.white.opacity(0.09), in: Capsule())
        }
        .buttonStyle(.plain)
    }

    private func iconChip(_ symbol: String, help: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 9, weight: .bold))
                .foregroundStyle(.white.opacity(0.7))
                .frame(width: 20, height: 20)
                .background(Color.white.opacity(0.09), in: Circle())
        }
        .buttonStyle(.plain)
        .help(help)
    }
}

private struct ContactRow: View {
    let person: LeadFounder
    @ObservedObject var model: LeadsModel
    let leadID: Int

    var body: some View {
        HStack(spacing: 5) {
            Text([person.name, person.title].compactMap { $0 }.joined(separator: " · "))
                .font(.system(size: 11))
                .foregroundStyle(.white.opacity(0.7))
                .lineLimit(1)
            Spacer(minLength: 4)
            if let email = person.email {
                let id = "e\(leadID)\(email)"
                Button { model.copy(email, id: id) } label: {
                    Image(systemName: model.copiedID == id ? "checkmark" : "envelope")
                }
                .buttonStyle(.plain)
                .help("Copy \(email)")
            }
            if let link = person.linkedin.flatMap(URL.init(string:)) {
                Button { NSWorkspace.shared.open(link) } label: {
                    Text("in").font(.system(size: 10, weight: .bold))
                }
                .buttonStyle(.plain)
                .help(link.absoluteString)
            }
        }
        .font(.system(size: 10))
        .foregroundStyle(.white.opacity(0.6))
    }
}

private struct EmailComposer: View {
    let lead: StartupLead
    @ObservedObject var model: LeadsModel
    let accent: Color
    @State private var to = ""
    @State private var subject = ""
    @State private var text = ""

    private var busy: Bool { model.busyIDs.contains(lead.id) }
    private var sent: Set<String> { lead.sentRecipients }
    private var recipients: [String] {
        let parsed = to.split(whereSeparator: { $0 == "," || $0 == " " }).map(String.init).filter { $0.contains("@") }
        var seen = Set<String>()
        return parsed.filter { seen.insert($0.lowercased()).inserted }
    }
    private var unsent: [String] { recipients.filter { !sent.contains($0.lowercased()) } }
    private var canSend: Bool { !busy && !unsent.isEmpty && !subject.isEmpty && !text.isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if lead.draftBody == nil {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.mini).tint(.white)
                    Text(busy ? "Drafting… finding the founder and writing your email" : "No draft yet")
                        .font(.system(size: 11)).foregroundStyle(.white.opacity(0.5))
                    if !busy {
                        Button("Draft now") { model.regenerate(lead) }
                            .buttonStyle(.plain)
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(accent)
                    }
                }
            } else {
                field("To", $to)
                if !people.isEmpty {
                    FlowChips(items: people) { person in
                        recipientChip(person)
                    }
                }
                field("Subject", $subject)
                TextEditor(text: $text)
                    .font(.system(size: 11))
                    .scrollContentBackground(.hidden)
                    .padding(6)
                    .frame(minHeight: 190)
                    .background(Color.black.opacity(0.25), in: RoundedRectangle(cornerRadius: 8))
                HStack(spacing: 6) {
                    Label("Sonali_Nayak_Resume.pdf", systemImage: "paperclip")
                        .font(.system(size: 10))
                        .foregroundStyle(.white.opacity(0.45))
                    Spacer()
                    Button { model.regenerate(lead) } label: { Image(systemName: "arrow.clockwise") }
                        .buttonStyle(.plain)
                        .foregroundStyle(.white.opacity(0.6))
                        .help("Redraft")
                        .disabled(busy)
                    Button { model.send(lead, to: unsent, subject: subject, body: text) } label: {
                        HStack(spacing: 4) {
                            Image(systemName: busy ? "hourglass" : "paperplane.fill")
                            Text(sendLabel)
                        }
                        .font(.system(size: 11.5, weight: .semibold))
                        .foregroundStyle(.black)
                        .padding(.horizontal, 12)
                        .frame(height: 24)
                        .background(canSend ? accent : Color.white.opacity(0.4), in: Capsule())
                    }
                    .buttonStyle(.plain)
                    .disabled(!canSend)
                    .help(unsent.count > 1 ? "Sends a separate email to each person, greeting them by name" : "")
                }
            }
        }
        .padding(.top, 4)
        .onAppear(perform: load)
        .onChange(of: lead.draftBody) { _, _ in load() }
    }

    private var sendLabel: String {
        if busy { return "Sending…" }
        if unsent.isEmpty && !recipients.isEmpty { return "Sent" }
        return unsent.count > 1 ? "Send to \(unsent.count)" : "Send"
    }

    private var people: [LeadFounder] {
        var seen = Set<String>()
        return lead.contacts.filter { p in
            guard let email = p.email?.lowercased() else { return false }
            return seen.insert(email).inserted
        }
    }

    private func recipientChip(_ person: LeadFounder) -> some View {
        let email = person.email ?? ""
        let done = sent.contains(email.lowercased())
        let on = recipients.contains { $0.lowercased() == email.lowercased() }
        let first = person.name?.split(separator: " ").first.map(String.init) ?? email
        return Button { toggle(email) } label: {
            HStack(spacing: 3) {
                Image(systemName: done ? "checkmark" : (on ? "checkmark.circle.fill" : "circle"))
                Text(first)
            }
            .font(.system(size: 10))
            .foregroundStyle(done ? .white.opacity(0.35) : (on ? .black : .white.opacity(0.7)))
            .padding(.horizontal, 7)
            .frame(height: 18)
            .background(done ? Color.white.opacity(0.04) : (on ? Color.white : Color.white.opacity(0.08)), in: Capsule())
        }
        .buttonStyle(.plain)
        .disabled(done)
        .help(done ? "Already emailed \(email)" : "\(person.title ?? "") · \(email)")
    }

    private func toggle(_ email: String) {
        var list = recipients
        if let i = list.firstIndex(where: { $0.lowercased() == email.lowercased() }) {
            list.remove(at: i)
        } else {
            list.append(email)
        }
        to = list.joined(separator: ", ")
    }

    private func load() {
        let first = lead.draftTo ?? lead.bestEmail ?? ""
        to = sent.contains(first.lowercased()) ? (people.compactMap(\.email).first { !sent.contains($0.lowercased()) } ?? "") : first
        subject = lead.draftSubject ?? ""
        text = lead.draftBody ?? ""
    }

    private func field(_ label: String, _ value: Binding<String>) -> some View {
        HStack(spacing: 6) {
            Text(label)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(.white.opacity(0.4))
                .frame(width: 44, alignment: .leading)
            TextField("", text: value)
                .textFieldStyle(.plain)
                .font(.system(size: 11.5))
                .foregroundStyle(.white)
        }
        .padding(.horizontal, 8)
        .frame(height: 24)
        .background(Color.black.opacity(0.25), in: RoundedRectangle(cornerRadius: 6))
    }
}

private struct FlowChips<Item, Content: View>: View {
    let items: [Item]
    let content: (Item) -> Content

    var body: some View {
        ScrollView(.horizontal) {
            HStack(spacing: 4) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in content(item) }
            }
        }
        .scrollIndicators(.never)
    }
}

enum Countries {
    static let regions: [(String, [String])] = [
        ("Nordics", ["Norway", "Sweden", "Denmark", "Finland", "Iceland"]),
        ("UK & Ireland", ["United Kingdom", "Ireland"]),
        ("Western Europe", ["Germany", "France", "Netherlands", "Belgium", "Luxembourg", "Switzerland", "Austria"]),
        ("Southern Europe", ["Spain", "Portugal", "Italy", "Greece", "Malta", "Cyprus"]),
        ("Central & Eastern Europe", ["Poland", "Czechia", "Slovakia", "Hungary", "Romania", "Bulgaria", "Slovenia", "Croatia", "Serbia", "Ukraine", "Moldova", "Albania", "North Macedonia", "Bosnia and Herzegovina", "Montenegro"]),
        ("Baltics", ["Estonia", "Latvia", "Lithuania"]),
        ("Middle East", ["United Arab Emirates", "Saudi Arabia", "Israel", "Qatar", "Turkey"]),
    ]

    static let ordered: [String] = regions.flatMap(\.1)
}

private struct CountryPicker: View {
    @ObservedObject var model: LeadsModel
    let accent: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(model.countries.isEmpty ? "Anywhere in Europe + Middle East" : "\(model.countries.count) selected")
                    .font(.system(size: 11, weight: .semibold))
                Spacer()
                if !model.countries.isEmpty {
                    Button("Clear") { model.countries = [] }
                        .buttonStyle(.plain)
                        .font(.system(size: 11))
                        .foregroundStyle(accent)
                }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    ForEach(Countries.regions, id: \.0) { region, countries in
                        VStack(alignment: .leading, spacing: 4) {
                            Button { model.toggle(region: countries) } label: {
                                HStack(spacing: 4) {
                                    Text(region.uppercased())
                                        .font(.system(size: 9.5, weight: .bold))
                                        .foregroundStyle(.secondary)
                                    Image(systemName: countries.allSatisfy(model.countries.contains) ? "checkmark.circle.fill" : "plus.circle")
                                        .font(.system(size: 9))
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .buttonStyle(.plain)
                            .help("Select all in \(region)")
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 104), spacing: 4)], alignment: .leading, spacing: 4) {
                                ForEach(countries, id: \.self) { country in
                                    let on = model.countries.contains(country)
                                    Button { model.toggle(country: country) } label: {
                                        HStack(spacing: 4) {
                                            Image(systemName: on ? "checkmark.square.fill" : "square")
                                                .foregroundStyle(on ? accent : .secondary)
                                            Text(country).lineLimit(1)
                                            Spacer(minLength: 0)
                                        }
                                        .font(.system(size: 11))
                                        .contentShape(Rectangle())
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                    }
                }
            }
            .frame(height: 300)
            Button {
                model.find()
            } label: {
                Text(model.countries.isEmpty ? "Find \(model.count) anywhere" : "Find \(model.count) in \(model.locationLabel)")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.black)
                    .frame(maxWidth: .infinity)
                    .frame(height: 26)
                    .background(accent, in: Capsule())
            }
            .buttonStyle(.plain)
            .disabled(model.isSearching)
        }
        .padding(12)
        .frame(width: 280)
    }
}
