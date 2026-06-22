import SwiftUI

struct HomeView: View {
    @StateObject private var vm: HomeViewModel
    @EnvironmentObject private var router: Router

    init(scheduleService: ScheduleDataServiceProtocol, authViewModel: AuthViewModel) {
        _vm = StateObject(wrappedValue: HomeViewModel(
            scheduleService: scheduleService,
            authViewModel: authViewModel
        ))
    }

    var body: some View {
        // HomeView is already inside SchedulerApp's NavigationStack — nesting another one
        // bound to the same router.path made the inner stack render the route's default text
        // ("home") instead of this content. The outer stack handles .scheduleList routing.
        Group {
            if vm.isLoading {
                ProgressView()
            } else if vm.hasInitComplete {
                content
            } else {
                ProgressView("Loading...")
            }
        }
        .navigationTitle("Home")
        .task {
            await vm.initialize()
        }
    }

    private var content: some View {
        ScrollView {
            VStack(spacing: 24) {
                greeting

                VStack(spacing: 16) {
                    Button(action: { router.push(.scheduleList) }) {
                        Label("My Schedules", systemImage: "calendar")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }

                    Button(action: { router.push(.scheduleBuilder) }) {
                        Label("Create New Schedule", systemImage: "plus.circle")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }

                    Button(action: { router.push(.archivedSchedules) }) {
                        Label("Archived Schedules", systemImage: "archivebox")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.purple)
                            .foregroundColor(.white)
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    }
                }
                .padding(.horizontal)

                if !vm.schedules.isEmpty {
                    recentSchedules
                }
            }
            .padding(.vertical)
        }
    }

    private var greeting: some View {
        Text("Hello, \(vm.displayName ?? "User")")
            .font(.title2)
            .fontWeight(.medium)
    }

    private var recentSchedules: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("\(vm.schedulesInvolvedCount) Schedules")
                .font(.headline)
                .padding(.horizontal)

            ForEach(vm.schedules) { schedule in
                VStack(alignment: .leading, spacing: 4) {
                    Text(schedule.name)
                        .fontWeight(.semibold)
                    Text(schedule.status.rawValue.capitalized)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                .padding()
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .padding(.horizontal)
            }
        }
    }
}

struct ScheduleListView: View {
    // Self-loading so it works regardless of the navigation entry point (the outer
    // NavigationStack builds this fresh). @StateObject so @Published changes re-render.
    @StateObject private var vm: HomeViewModel

    init(scheduleService: ScheduleDataServiceProtocol, authViewModel: AuthViewModel) {
        _vm = StateObject(wrappedValue: HomeViewModel(scheduleService: scheduleService, authViewModel: authViewModel))
    }

    var body: some View {
        Group {
            if vm.isLoading && vm.schedules.isEmpty {
                ProgressView()
            } else {
                List(vm.schedules) { schedule in
                    NavigationLink(value: Route.scheduleDetail(schedule.id)) {
                        VStack(alignment: .leading) {
                            Text(schedule.name).fontWeight(.semibold)
                            Text(schedule.status.rawValue.capitalized).font(.caption)
                        }
                    }
                }
            }
        }
        .navigationTitle("My Schedules")
        .task { await vm.initialize() }
    }
}
