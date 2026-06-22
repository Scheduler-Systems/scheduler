import Foundation

// Legal Center: Privacy Policy + Terms & Conditions both open the same external legal
// center URL (parity with Flutter's LegalDocumentsHelper). Single source of truth.
enum LegalDocuments {
    static let legalCenterURLString = "https://scheduler-systems.com/legal"
    static var legalCenterURL: URL { URL(string: legalCenterURLString)! }
}
